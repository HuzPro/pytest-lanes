"""``--lane=<name>`` parsing and per-item filtering."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Protocol

import pytest

from pytest_lanes.config import LaneConfig
from pytest_lanes.lanes import ClassifiableItem, lane_for_item, other_lane_ignores


class MarkableItem(ClassifiableItem, Protocol):
    """A classifiable item that can also carry pytest markers."""

    def add_marker(self, marker: object) -> None: ...


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
    """Return ``(positional_args, ignore_paths)`` for an in-process ``--lane=`` run."""
    positional: list[str] = []
    ignores: list[str] = []

    for name in selected:
        spec = lane_config.lane_by_name(name)
        if spec is None:
            continue
        positional.extend(spec.subprocess_paths)
        positional.extend(spec.subprocess_nodeids)
        ignores.extend(spec.subprocess_ignore)
        if spec.subprocess_ignore_other_lanes:
            ignores.extend(other_lane_ignores(spec, lane_config))

    return positional, list(dict.fromkeys(ignores))


def apply_lane_filter(
    items: Iterable[MarkableItem],
    rootpath: Path,
    lane_config: LaneConfig,
    selected_lanes: tuple[str, ...],
    marker_factory: Callable[[str], object],
) -> None:
    """Mark each item with its lane's marker and skip items outside the selection."""
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
            # Advisory without a --lane selection; a real config error under one.
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
