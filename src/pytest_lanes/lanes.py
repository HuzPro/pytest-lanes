"""Lane classification and subprocess argv construction.

Two pure functions consumed by the plugin hooks:

* :func:`lane_for_item` — given a collected pytest item, return the
  :class:`~pytest_lanes.config.LaneSpec` that owns it. Class-base-name
  matches outrank path-based rules so container-backed tests follow the
  container regardless of where their file lives.
* :func:`build_lane_commands` — emit one :class:`LaneCommand` per lane
  subprocess for the selected mode (``"standard"`` or ``"full"``), wired with
  ``--ignore=`` flags derived from sibling lanes when
  ``subprocess_ignore_other_lanes`` is set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec


@dataclass(frozen=True)
class LaneCommand:
    """One lane subprocess: its pytest argv (minus the interpreter) and env overrides."""

    name: str
    args: tuple[str, ...]
    env_set: tuple[tuple[str, str], ...] = ()


def relative_test_path(item: object, rootpath: Path) -> str:
    item_path = Path(str(item.path))
    try:
        return item_path.relative_to(rootpath).as_posix()
    except ValueError:
        return item_path.as_posix()


def lane_for_item(
    item: object, rootpath: Path, lane_config: LaneConfig
) -> LaneSpec:
    """Return the lane that owns this test item.

    Resolution order:
        1. ``classifier_class_base_names`` — promotes container-backed tests
           into their container lane regardless of file path.
        2. ``classifier_paths`` / ``classifier_path_suffix`` /
           ``classifier_path_prefixes`` in lane declaration order.
        3. The lane declared with ``classifier_fallback = true``.
    """
    class_match = _lane_by_class_base_name(item, lane_config)
    if class_match is not None:
        return class_match

    relative_path = relative_test_path(item, rootpath)
    for spec in lane_config.lanes:
        if _classifier_matches_path(spec, relative_path):
            return spec

    fallback = lane_config.fallback_lane()
    if fallback is not None:
        return fallback

    raise LookupError(
        f"No lane classified test path '{relative_path}' and no fallback lane is declared."
    )


def _lane_by_class_base_name(item: object, lane_config: LaneConfig) -> LaneSpec | None:
    test_class = getattr(item, "cls", None)
    if not isinstance(test_class, type):
        return None

    mro_names = {base.__name__ for base in test_class.__mro__}
    for spec in lane_config.lanes:
        if not spec.classifier_class_base_names:
            continue
        if any(name in mro_names for name in spec.classifier_class_base_names):
            return spec
    return None


def _classifier_matches_path(spec: LaneSpec, relative_path: str) -> bool:
    if relative_path in spec.classifier_paths:
        return True

    if spec.classifier_path_suffix and relative_path.endswith(spec.classifier_path_suffix):
        return True

    for prefix in spec.classifier_path_prefixes:
        normalized = prefix.rstrip("/")
        if relative_path == normalized:
            return True
        if relative_path.startswith(normalized + "/"):
            return True

    return False


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
        args: list[str] = [*passthrough_args, "--color=no"]
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
            )
        )

    return commands


def other_lane_ignores(
    excluded_spec: LaneSpec, lane_config: LaneConfig
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for spec in lane_config.lanes:
        if spec.name == excluded_spec.name:
            continue
        for path in (*spec.subprocess_paths, *spec.classifier_paths):
            if path in seen:
                continue
            seen.add(path)
            ordered.append(path)
        for prefix in spec.classifier_path_prefixes:
            normalized = prefix.rstrip("/")
            if normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
    return ordered
