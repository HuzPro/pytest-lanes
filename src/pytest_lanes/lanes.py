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


@dataclass(frozen=True)
class LaneAssignment:
    """Which lane claimed an item, via which classifier rule and matched value."""

    lane: LaneSpec
    rule_kind: str
    matched_value: str


def lane_for_item(item: object, rootpath: Path, lane_config: LaneConfig) -> LaneSpec:
    """Return the lane that owns this test item.

    Delegates to :func:`explain_lane_for_item` so classification has exactly
    one code path — what ``--lanes-explain`` reports is what runs.
    """
    return explain_lane_for_item(item, rootpath, lane_config).lane


def explain_lane_for_item(
    item: object, rootpath: Path, lane_config: LaneConfig
) -> LaneAssignment:
    """Return the lane that owns this test item and the rule that claimed it.

    Resolution order:
        1. ``classifier_class_base_names`` — promotes container-backed tests
           into their container lane regardless of file path.
        2. ``classifier_paths`` / ``classifier_path_suffix`` /
           ``classifier_path_prefixes`` in lane declaration order.
        3. The lane declared with ``classifier_fallback = true``.
    """
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


def other_lane_ignores(excluded_spec: LaneSpec, lane_config: LaneConfig) -> list[str]:
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
