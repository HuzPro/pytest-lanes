"""``--lane=<name>`` parsing and per-item filtering.

These functions are pure: they take their inputs (CLI value, items list,
:class:`~pytest_lanes.config.LaneConfig`) and return / mutate without
touching pytest internals beyond raising :class:`pytest.UsageError` for
invalid lane names. The hook layer in :mod:`pytest_lanes.hooks` wires
them up to real pytest.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path

import pytest

from pytest_lanes.config import LaneConfig
from pytest_lanes.lanes import lane_for_item, other_lane_ignores


def parse_lane_selection(value: str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    stripped = value.strip()
    if not stripped:
        return ()
    return tuple(name.strip() for name in stripped.split(",") if name.strip())


def validate_lane_names(selected: tuple[str, ...], lane_config: LaneConfig) -> None:
    known = {spec.name for spec in lane_config.lanes}
    unknown = [name for name in selected if name not in known]
    if not unknown:
        return
    known_list = ", ".join(spec.name for spec in lane_config.lanes)
    raise pytest.UsageError(
        f"Unknown --lane name(s): {', '.join(unknown)}. Known lanes: {known_list}."
    )


def collection_args_for_lanes(
    selected: tuple[str, ...], lane_config: LaneConfig
) -> tuple[list[str], list[str]]:
    """Return ``(positional_args, ignore_paths)`` for an in-process ``--lane=`` run.

    Mirrors the argv that :func:`pytest_lanes.lanes.build_lane_commands`
    would produce for a subprocess on the same lane, so pytest's collection
    phase only imports the lane's own files. Without this, ``pytest --lane=X``
    would let pytest discover every file under rootdir and fail on imports
    from unrelated lanes that are not installed in the current environment.
    """
    positional: list[str] = []
    ignores: list[str] = []
    seen_ignores: set[str] = set()

    def _record_ignore(path: str) -> None:
        if path in seen_ignores:
            return
        seen_ignores.add(path)
        ignores.append(path)

    for name in selected:
        spec = lane_config.lane_by_name(name)
        if spec is None:
            continue
        positional.extend(spec.subprocess_paths)
        positional.extend(spec.subprocess_nodeids)
        for ignore_path in spec.subprocess_ignore:
            _record_ignore(ignore_path)
        if spec.subprocess_ignore_other_lanes:
            for ignore_path in other_lane_ignores(spec, lane_config):
                _record_ignore(ignore_path)

    return positional, ignores


def apply_lane_filter(
    items: Iterable[object],
    rootpath: Path,
    lane_config: LaneConfig,
    selected_lanes: tuple[str, ...],
    marker_factory: Callable[[str], object],
) -> None:
    """Mark each item with its lane's marker and skip items outside the selection.

    ``marker_factory`` builds a marker object given a name; the plugin passes
    ``getattr(pytest.mark, name)`` so tests can substitute a lightweight stub.
    When ``selected_lanes`` is empty no items are skipped — every collected
    item runs in its native lane.
    """
    if selected_lanes:
        validate_lane_names(selected_lanes, lane_config)

    selected = set(selected_lanes)
    skip_reason = (
        f"Test filtered out by --lane={','.join(selected_lanes)}."
        if selected_lanes
        else ""
    )

    for item in items:
        try:
            spec = lane_for_item(item, rootpath, lane_config)
        except LookupError:
            # Without a --lane selection, marking is advisory: orchestration
            # has stepped aside (-k, -m, targeted paths) and plain pytest may
            # collect tests the lanes never claim. Crashing collection over
            # those would punish filtering. Under a selection the error
            # stands: classifiers and subprocess paths disagree.
            if selected:
                raise
            continue
        if spec.marker:
            item.add_marker(marker_factory(spec.marker))

        if not selected:
            continue
        if spec.name in selected:
            continue

        item.add_marker(pytest.mark.skip(reason=skip_reason))
