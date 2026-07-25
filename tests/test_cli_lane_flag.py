"""Behavioral tests for the ``--lane=<name>[,<name>...]`` CLI surface."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.lane_selection import (
    apply_lane_filter,
    collection_args_for_lanes,
    parse_lane_selection,
    validate_lane_names,
)
from tests.test_lane_assignment import (
    _example_lane_config,
    _FakeItem,
)


class _MarkerStub:
    def __init__(self, name: str) -> None:
        self.name = name


class _ItemWithMarkers(_FakeItem):
    def __init__(self, path: Path, nodeid: str, test_class: type | None = None) -> None:
        super().__init__(path, nodeid, test_class)
        self.added_markers: list[object] = []

    def add_marker(self, marker: object) -> None:
        self.added_markers.append(marker)


def _marker_names(item: _ItemWithMarkers) -> set[str]:
    return {
        getattr(marker, "name", "")
        for marker in item.added_markers
        if getattr(marker, "name", None)
    }


def test_parse_lane_selection_returns_empty_tuple_for_none_value() -> None:
    assert parse_lane_selection(None) == ()


def test_parse_lane_selection_splits_comma_separated_names() -> None:
    assert parse_lane_selection("postgres, timescale,acceptance ") == (
        "postgres",
        "timescale",
        "acceptance",
    )


def test_validate_lane_names_raises_usage_error_for_unknown_lane() -> None:
    config = _example_lane_config()

    with pytest.raises(pytest.UsageError, match="ghost_lane"):
        validate_lane_names(("postgres", "ghost_lane"), config)


def test_apply_lane_filter_marks_every_item_with_its_lane_marker() -> None:
    config = _example_lane_config()
    root = Path("C:/repo")
    postgres_item = _ItemWithMarkers(
        path=root / "backend" / "postgres" / "tests" / "test_x.py",
        nodeid="backend/postgres/tests/test_x.py::t",
    )
    unit_item = _ItemWithMarkers(
        path=root / "app" / "tests" / "test_normal.py",
        nodeid="app/tests/test_normal.py::t",
    )

    apply_lane_filter(
        items=[postgres_item, unit_item],
        rootpath=root,
        lane_config=config,
        selected_lanes=(),
        marker_factory=_MarkerStub,
    )

    assert "postgres_integration" in _marker_names(postgres_item)
    assert "unit" in _marker_names(unit_item)


def test_apply_lane_filter_skips_items_outside_selected_lanes() -> None:
    config = _example_lane_config()
    root = Path("C:/repo")
    postgres_item = _ItemWithMarkers(
        path=root / "backend" / "postgres" / "tests" / "test_x.py",
        nodeid="backend/postgres/tests/test_x.py::t",
    )
    unit_item = _ItemWithMarkers(
        path=root / "app" / "tests" / "test_normal.py",
        nodeid="app/tests/test_normal.py::t",
    )

    apply_lane_filter(
        items=[postgres_item, unit_item],
        rootpath=root,
        lane_config=config,
        selected_lanes=("other",),
        marker_factory=_MarkerStub,
    )

    assert "skip" in _marker_names(postgres_item)
    assert "skip" not in _marker_names(unit_item)


def _no_fallback_lane_config() -> LaneConfig:
    return LaneConfig(
        lanes=(
            LaneSpec(
                name="postgres",
                marker="postgres_integration",
                classifier_path_prefixes=("backend/postgres/",),
            ),
        )
    )


def test_apply_lane_filter_leaves_unclassifiable_items_unmarked_without_a_selection() -> (
    None
):
    # Arrange: a config with no fallback lane, and an item (say, an example
    # under docs/) that no lane classifies. This happens whenever
    # orchestration steps aside (-k, -m) and plain pytest collects paths the
    # lanes never claim.
    config = _no_fallback_lane_config()
    root = Path("C:/repo")
    unclaimed_item = _ItemWithMarkers(
        path=root / "docs" / "examples" / "test_handler.py",
        nodeid="docs/examples/test_handler.py::t",
    )

    # Act: marking is advisory when no --lane selection is active - it must
    # not crash collection over a test the lanes simply do not know.
    apply_lane_filter(
        items=[unclaimed_item],
        rootpath=root,
        lane_config=config,
        selected_lanes=(),
        marker_factory=_MarkerStub,
    )

    # Assert
    assert unclaimed_item.added_markers == []


def test_apply_lane_filter_stays_loud_for_unclassifiable_items_under_a_selection() -> (
    None
):
    # Arrange: same unclaimed item, but the caller asked for lane semantics
    # (--lane=postgres, or a lane child selecting its own tests).
    config = _no_fallback_lane_config()
    root = Path("C:/repo")
    unclaimed_item = _ItemWithMarkers(
        path=root / "docs" / "examples" / "test_handler.py",
        nodeid="docs/examples/test_handler.py::t",
    )

    # Act / Assert: an unclassifiable item under an explicit lane selection
    # means classifiers and subprocess paths disagree - stay loud.
    with pytest.raises(LookupError, match="docs/examples/test_handler.py"):
        apply_lane_filter(
            items=[unclaimed_item],
            rootpath=root,
            lane_config=config,
            selected_lanes=("postgres",),
            marker_factory=_MarkerStub,
        )


def test_collection_args_restrict_pytest_to_postgres_lane_paths() -> None:
    config = _example_lane_config()

    positional, ignores = collection_args_for_lanes(("postgres",), config)

    assert "backend/postgres/tests" in positional
    assert "app/tests/test_first_run_configuration_service.py" in positional
    assert "backend/postgres/tests/test_sensor_logger.py" in ignores


def test_collection_args_for_other_lane_expands_into_ignore_other_lanes_union() -> None:
    config = _example_lane_config()

    positional, ignores = collection_args_for_lanes(("other",), config)

    # The 'other' lane has no positional paths — collection defaults to rootdir,
    # then every other lane's paths are added as --ignore= entries.
    assert positional == []
    assert "backend/postgres/tests" in ignores
    assert "backend/http_adapter/tests" in ignores
    assert "test_full_build_verification.py" in ignores
    # Explicit subprocess_ignore entries also land in the ignore list.
    assert "experiments" in ignores


def test_collection_args_for_multiple_lanes_union_the_positional_args() -> None:
    config = _example_lane_config()

    positional, _ = collection_args_for_lanes(("postgres", "timescale"), config)

    assert "backend/postgres/tests" in positional
    assert "backend/postgres/tests/test_sensor_logger.py" in positional


def test_apply_lane_filter_admits_multiple_selected_lanes() -> None:
    config = _example_lane_config()
    root = Path("C:/repo")
    postgres_item = _ItemWithMarkers(
        path=root / "backend" / "postgres" / "tests" / "test_x.py",
        nodeid="backend/postgres/tests/test_x.py::t",
    )
    timescale_item = _ItemWithMarkers(
        path=root / "backend" / "postgres" / "tests" / "test_sensor_logger.py",
        nodeid="backend/postgres/tests/test_sensor_logger.py::t",
    )
    unit_item = _ItemWithMarkers(
        path=root / "app" / "tests" / "test_normal.py",
        nodeid="app/tests/test_normal.py::t",
    )

    apply_lane_filter(
        items=[postgres_item, timescale_item, unit_item],
        rootpath=root,
        lane_config=config,
        selected_lanes=("postgres", "timescale"),
        marker_factory=_MarkerStub,
    )

    assert "skip" not in _marker_names(postgres_item)
    assert "skip" not in _marker_names(timescale_item)
    assert "skip" in _marker_names(unit_item)
