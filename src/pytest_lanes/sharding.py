"""Static shard planning: decide before launch whether to split a lane."""

from __future__ import annotations

import heapq
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.durations import LaneRecord
from pytest_lanes.lanes import LaneCommand, build_lane_commands, other_lane_ignores

SHARD_REBALANCE_IMBALANCE_RATIO = 0.20
_SHARD_PLAN_FILENAME = "shard_plan.json"


def shard_plan_path_for_rootdir(rootpath: Path) -> Path:
    return rootpath / ".pytest_cache" / "v" / "pytest-lanes" / _SHARD_PLAN_FILENAME


def persist_first_shard(
    path: Path, lane_name: str, first_shard_files: tuple[str, ...]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"lane": lane_name, "first_shard_files": list(first_shard_files)}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def load_persisted_plan(path: Path) -> tuple[str, tuple[str, ...]] | None:
    """Return ``(lane_name, first_shard_files)`` or ``None``."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(raw, dict):
        return None
    lane = raw.get("lane")
    files = raw.get("first_shard_files")
    if not isinstance(lane, str) or not isinstance(files, list):
        return None
    return lane, tuple(str(entry) for entry in files)


@dataclass(frozen=True)
class ShardPlan:
    """The deterministic outcome of shard planning for one run."""

    commands: tuple[LaneCommand, ...]
    sharded_lane: str = ""
    first_shard_files: tuple[str, ...] = ()
    shard_parents: tuple[tuple[str, str], ...] = ()
    reproduce_lines: tuple[tuple[str, tuple[str, ...]], ...] = ()
    notes: tuple[str, ...] = ()


def simulate_makespan(durations: Sequence[float], max_workers: int) -> float:
    """Project the wall time of running lanes on the bounded pool."""
    if not durations:
        return 0.0

    queued = sorted(durations, reverse=True)
    running: list[float] = []
    for duration in queued:
        if len(running) < max_workers:
            heapq.heappush(running, duration)
            continue
        freed_at = heapq.heappop(running)
        heapq.heappush(running, freed_at + duration)

    return max(running)


def plan_shards(
    mode: str,
    passthrough_args: tuple[str, ...],
    lane_config: LaneConfig,
    records: Mapping[str, LaneRecord],
    max_workers: int,
    file_exists: Callable[[str], bool],
    persisted_plan: tuple[str, tuple[str, ...]] | None = None,
) -> ShardPlan:
    """Decide whether to split the longest divisible lane into two shards."""
    commands = tuple(
        build_lane_commands(
            mode=mode, passthrough_args=passthrough_args, lane_config=lane_config
        )
    )
    unsharded = ShardPlan(commands=commands)

    candidate = _shard_candidate(commands, lane_config, records)
    if candidate is None:
        return unsharded
    spec, record = candidate

    if max_workers < 2:
        return unsharded

    scheduled_names = [command.name for command in commands]
    if any(name not in records for name in scheduled_names):
        return unsharded

    existing_files = tuple(
        (path, seconds) for path, seconds in record.files if file_exists(path)
    )
    if len(existing_files) < 2:
        return unsharded

    persisted_first_shard = (
        persisted_plan[1]
        if persisted_plan is not None and persisted_plan[0] == spec.name
        else None
    )
    first_half, second_half, recut_note = _choose_cut(
        existing_files, persisted_first_shard
    )
    shard_seconds = _projected_shard_seconds(record, first_half, second_half)

    unsharded_makespan = simulate_makespan(
        [records[name].total for name in scheduled_names], max_workers
    )
    sharded_durations = [
        records[name].total for name in scheduled_names if name != spec.name
    ] + list(shard_seconds)
    sharded_makespan = simulate_makespan(sharded_durations, max_workers)

    gain = unsharded_makespan - sharded_makespan
    if gain < lane_config.shard_min_saving:
        return unsharded

    first_shard_files = tuple(path for path, _ in first_half)
    shard_commands = _shard_commands(
        spec, lane_config, passthrough_args, first_shard_files
    )
    notes = [
        (
            f"sharded {spec.name} into 2: projected "
            f"{shard_seconds[0]:.1f}s + {shard_seconds[1]:.1f}s, makespan gain "
            f"{gain:.1f}s >= {lane_config.shard_min_saving:.1f}s"
        )
    ]
    if recut_note:
        notes.insert(0, recut_note)

    return ShardPlan(
        commands=_with_replacement(commands, spec.name, shard_commands),
        sharded_lane=spec.name,
        first_shard_files=first_shard_files,
        shard_parents=(
            (shard_commands[0].name, spec.name),
            (shard_commands[1].name, spec.name),
        ),
        reproduce_lines=(
            (
                shard_commands[0].name,
                (
                    f"pytest --lane={spec.name}",
                    "pytest " + " ".join(first_shard_files),
                ),
            ),
            (
                shard_commands[1].name,
                (
                    f"pytest --lane={spec.name}",
                    "pytest "
                    + " ".join(
                        [
                            *spec.subprocess_paths,
                            *(f"--ignore={path}" for path in first_shard_files),
                        ]
                    ),
                ),
            ),
        ),
        notes=tuple(notes),
    )


def _shard_candidate(
    commands: tuple[LaneCommand, ...],
    lane_config: LaneConfig,
    records: Mapping[str, LaneRecord],
) -> tuple[LaneSpec, LaneRecord] | None:
    """The single longest recorded lane that opted in and can be split."""
    candidates: list[tuple[LaneSpec, LaneRecord]] = []
    for command in commands:
        spec = lane_config.lane_by_name(command.name)
        if spec is None or not spec.divisible:
            continue
        if spec.lane_numprocesses is not None:
            continue
        record = records.get(spec.name)
        if record is None or len(record.files) < 2:
            continue
        candidates.append((spec, record))
    if not candidates:
        return None
    return max(candidates, key=lambda entry: entry[1].total)


def _choose_cut(
    files: tuple[tuple[str, float], ...],
    persisted_first_shard: tuple[str, ...] | None,
) -> tuple[tuple[tuple[str, float], ...], tuple[tuple[str, float], ...], str]:
    """Prefer the persisted cut while it stays balanced; re-cut loudly."""
    fresh_first, fresh_second = contiguous_halves(files)

    if persisted_first_shard is None:
        return fresh_first, fresh_second, ""

    persisted = set(persisted_first_shard)
    known = {path for path, _ in files}
    if not persisted <= known:
        return fresh_first, fresh_second, _recut_note(fresh_first)

    kept_first = tuple(entry for entry in files if entry[0] in persisted)
    kept_second = tuple(entry for entry in files if entry[0] not in persisted)
    if not kept_first or not kept_second:
        return fresh_first, fresh_second, _recut_note(fresh_first)

    first_seconds = sum(seconds for _, seconds in kept_first)
    second_seconds = sum(seconds for _, seconds in kept_second)
    imbalance = abs(first_seconds - second_seconds) / max(first_seconds, second_seconds)
    if imbalance <= SHARD_REBALANCE_IMBALANCE_RATIO:
        return kept_first, kept_second, ""

    return fresh_first, fresh_second, _recut_note(fresh_first)


def _recut_note(fresh_first: tuple[tuple[str, float], ...]) -> str:
    boundary = fresh_first[-1][0] if fresh_first else "?"
    return (
        "shard plan re-cut: recorded durations drifted beyond "
        f"{SHARD_REBALANCE_IMBALANCE_RATIO:.0%}; new cut after {boundary}"
    )


def _projected_shard_seconds(
    record: LaneRecord,
    first_half: tuple[tuple[str, float], ...],
    second_half: tuple[tuple[str, float], ...],
) -> tuple[float, float]:
    """Each shard re-pays measured startup + collect."""
    files_seconds = sum(seconds for _, seconds in record.files)
    residual = max(record.total - record.startup - record.collect - files_seconds, 0.0)
    fixed = record.startup + record.collect + residual / 2
    return (
        fixed + sum(seconds for _, seconds in first_half),
        fixed + sum(seconds for _, seconds in second_half),
    )


def _shard_commands(
    spec: LaneSpec,
    lane_config: LaneConfig,
    passthrough_args: tuple[str, ...],
    first_shard_files: tuple[str, ...],
) -> tuple[LaneCommand, LaneCommand]:
    base = [*passthrough_args, "--color=no", "-p", "no:cacheprovider"]

    first = LaneCommand(
        name=f"{spec.name}~1of2",
        args=(*base, *first_shard_files),
        env_set=spec.subprocess_env_set,
    )

    second_args = [*base, *spec.subprocess_paths, *spec.subprocess_nodeids]
    second_args.extend(f"--ignore={path}" for path in first_shard_files)
    second_args.extend(f"--ignore={path}" for path in spec.subprocess_ignore)
    if spec.subprocess_ignore_other_lanes:
        second_args.extend(
            f"--ignore={path}" for path in other_lane_ignores(spec, lane_config)
        )
    # Shard 2 ignore-lists shard 1's files, so files added since recording still run.
    second = LaneCommand(
        name=f"{spec.name}~2of2",
        args=tuple(second_args),
        env_set=spec.subprocess_env_set,
        tolerate_no_tests=True,
    )
    return first, second


def _with_replacement(
    commands: tuple[LaneCommand, ...],
    lane_name: str,
    shard_commands: tuple[LaneCommand, LaneCommand],
) -> tuple[LaneCommand, ...]:
    replaced: list[LaneCommand] = []
    for command in commands:
        if command.name == lane_name:
            replaced.extend(shard_commands)
        else:
            replaced.append(command)
    return tuple(replaced)


def contiguous_halves(
    files: tuple[tuple[str, float], ...],
) -> tuple[tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]:
    """Cut the file list at the point that best balances the two halves."""
    total = sum(seconds for _, seconds in files)
    best_cut = 1
    best_imbalance = float("inf")
    running = 0.0
    for index, (_, seconds) in enumerate(files[:-1], start=1):
        running += seconds
        imbalance = abs(running - (total - running))
        if imbalance < best_imbalance:
            best_imbalance = imbalance
            best_cut = index
    return files[:best_cut], files[best_cut:]
