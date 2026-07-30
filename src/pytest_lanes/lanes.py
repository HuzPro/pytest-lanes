"""Lane classification and subprocess argv construction."""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec

# Every test in one file shares that file's path, so a suite of thousands of items
# resolves only as many distinct paths as it has test files.
_RELATIVE_PATH_CACHE_SIZE = 8192


@dataclass(frozen=True)
class LaneCommand:
    """One lane subprocess: its pytest argv (minus the interpreter) and env overrides."""

    name: str
    args: tuple[str, ...]
    env_set: tuple[tuple[str, str], ...] = ()
    tolerate_no_tests: bool = False


def relative_test_path(item: object, rootpath: Path) -> str:
    return _relative_posix_path(str(item.path), str(rootpath))


@lru_cache(maxsize=_RELATIVE_PATH_CACHE_SIZE)
def _relative_posix_path(item_path_value: str, rootpath_value: str) -> str:
    item_path = Path(item_path_value)
    try:
        return item_path.relative_to(Path(rootpath_value)).as_posix()
    except ValueError:
        return item_path.as_posix()


@dataclass(frozen=True)
class LaneAssignment:
    """Which lane claimed an item, via which classifier rule and matched value."""

    lane: LaneSpec
    rule_kind: str
    matched_value: str


def lane_for_item(item: object, rootpath: Path, lane_config: LaneConfig) -> LaneSpec:
    """Return the lane that owns this test item."""
    return explain_lane_for_item(item, rootpath, lane_config).lane


def explain_lane_for_item(
    item: object, rootpath: Path, lane_config: LaneConfig
) -> LaneAssignment:
    """Return the lane that owns this test item and the rule that claimed it."""
    class_assignment = _class_base_name_assignment(item, lane_config)
    if class_assignment is not None:
        return class_assignment

    relative_path = relative_test_path(item, rootpath)
    for spec in lane_config.lanes:
        path_assignment = _path_rule_assignment(spec, relative_path)
        if path_assignment is not None:
            return path_assignment

    fallback = lane_config.fallback_lane()
    if fallback is not None:
        return LaneAssignment(
            lane=fallback, rule_kind="classifier_fallback", matched_value=""
        )

    raise LookupError(
        f"No lane classified test path '{relative_path}' and no fallback lane is declared."
    )


def _class_base_name_assignment(
    item: object, lane_config: LaneConfig
) -> LaneAssignment | None:
    test_class = getattr(item, "cls", None)
    if not isinstance(test_class, type):
        return None

    mro_names = {base.__name__ for base in test_class.__mro__}
    for spec in lane_config.lanes:
        for base_name in spec.classifier_class_base_names:
            if base_name in mro_names:
                return LaneAssignment(
                    lane=spec,
                    rule_kind="classifier_class_base_names",
                    matched_value=base_name,
                )
    return None


def _path_rule_assignment(spec: LaneSpec, relative_path: str) -> LaneAssignment | None:
    if relative_path in spec.classifier_paths:
        return LaneAssignment(
            lane=spec, rule_kind="classifier_paths", matched_value=relative_path
        )

    if spec.classifier_path_suffix and relative_path.endswith(
        spec.classifier_path_suffix
    ):
        return LaneAssignment(
            lane=spec,
            rule_kind="classifier_path_suffix",
            matched_value=spec.classifier_path_suffix,
        )

    for prefix in spec.classifier_path_prefixes:
        normalized = prefix.rstrip("/")
        if relative_path == normalized or relative_path.startswith(normalized + "/"):
            return LaneAssignment(
                lane=spec, rule_kind="classifier_path_prefixes", matched_value=prefix
            )

    return None


def build_lane_commands(
    mode: str,
    passthrough_args: tuple[str, ...],
    lane_config: LaneConfig,
) -> list[LaneCommand]:
    """Build one :class:`LaneCommand` per subprocess lane for the given mode."""
    if mode == "full":
        lane_specs = lane_config.full_subprocess_lanes()
    else:
        lane_specs = lane_config.standard_subprocess_lanes()

    commands: list[LaneCommand] = []
    for spec in lane_specs:
        # Concurrent children racing on .pytest_cache break collection and clobber lastfailed.
        args: list[str] = [*passthrough_args, "--color=no", "-p", "no:cacheprovider"]
        if spec.lane_numprocesses is not None:
            # loadfile keeps each file on one worker, preserving in-file ordering.
            args.extend(["-n", str(spec.lane_numprocesses), "--dist", "loadfile"])
        args.extend(spec.subprocess_paths)
        args.extend(spec.subprocess_nodeids)
        for ignore_path in spec.subprocess_ignore:
            args.append(f"--ignore={ignore_path}")

        if spec.subprocess_ignore_other_lanes:
            for other_path in other_lane_ignores(spec, lane_config):
                args.append(f"--ignore={other_path}")

        commands.append(
            LaneCommand(
                name=spec.name,
                args=tuple(args),
                env_set=spec.subprocess_env_set,
                tolerate_no_tests=spec.tolerate_no_tests,
            )
        )

    return commands


def other_lane_ignores(excluded_spec: LaneSpec, lane_config: LaneConfig) -> list[str]:
    paths = [
        path
        for spec in lane_config.lanes
        if spec.name != excluded_spec.name
        for path in (
            *spec.subprocess_paths,
            *spec.classifier_paths,
            *(prefix.rstrip("/") for prefix in spec.classifier_path_prefixes),
        )
    ]
    return list(dict.fromkeys(paths))
