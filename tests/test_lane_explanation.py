"""Behavioral tests for lane-assignment explanations (``--lanes-explain``).

``explain_lane_for_item`` is the single classification code path: it returns
not just the owning lane but the classifier rule that claimed the item, so
what ``--lanes-explain`` prints can never drift from what actually runs.
"""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.explain import format_lane_explanation
from pytest_lanes.lanes import LaneAssignment, explain_lane_for_item, lane_for_item
from tests.test_lane_assignment import _example_lane_config, _FakeItem

_ROOT = Path("C:/repo")
_CONFIG = _example_lane_config()


def test_class_base_name_match_is_explained_with_the_matching_base_name() -> None:
    class PostgresTestCase:
        pass

    class TestActivityStore(PostgresTestCase):
        pass

    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_activity_store.py",
        nodeid="app/tests/test_activity_store.py::TestActivityStore::test_saves",
        test_class=TestActivityStore,
    )

    assignment = explain_lane_for_item(item, _ROOT, _CONFIG)

    assert assignment.lane.name == "postgres"
    assert assignment.rule_kind == "classifier_class_base_names"
    assert assignment.matched_value == "PostgresTestCase"


def test_exact_path_match_is_explained_with_the_path() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "postgres" / "tests" / "test_sensor_logger.py",
        nodeid="backend/postgres/tests/test_sensor_logger.py::test_logs",
    )

    assignment = explain_lane_for_item(item, _ROOT, _CONFIG)

    assert assignment.lane.name == "timescale"
    assert assignment.rule_kind == "classifier_paths"
    assert assignment.matched_value == "backend/postgres/tests/test_sensor_logger.py"


def test_path_prefix_match_is_explained_with_the_configured_prefix() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "http_adapter" / "tests" / "test_routes.py",
        nodeid="backend/http_adapter/tests/test_routes.py::test_get",
    )

    assignment = explain_lane_for_item(item, _ROOT, _CONFIG)

    assert assignment.lane.name == "http_adapter"
    assert assignment.rule_kind == "classifier_path_prefixes"
    assert assignment.matched_value == "backend/http_adapter/tests/"


def test_path_suffix_match_is_explained_with_the_suffix() -> None:
    config = LaneConfig(
        lanes=(
            LaneSpec(
                name="performance",
                marker="performance",
                classifier_path_suffix="_performance.py",
            ),
            LaneSpec(name="other", marker="unit", classifier_fallback=True),
        )
    )
    item = _FakeItem(
        path=_ROOT / "tests" / "test_api_performance.py",
        nodeid="tests/test_api_performance.py::test_latency",
    )

    assignment = explain_lane_for_item(item, _ROOT, config)

    assert assignment.lane.name == "performance"
    assert assignment.rule_kind == "classifier_path_suffix"
    assert assignment.matched_value == "_performance.py"


def test_fallback_lane_is_explained_as_fallback_with_no_matched_value() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_unclaimed.py",
        nodeid="app/tests/test_unclaimed.py::test_something",
    )

    assignment = explain_lane_for_item(item, _ROOT, _CONFIG)

    assert assignment.lane.name == "other"
    assert assignment.rule_kind == "classifier_fallback"
    assert assignment.matched_value == ""


def test_lane_for_item_and_explanation_always_agree() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "postgres" / "tests" / "test_activity_logger.py",
        nodeid="backend/postgres/tests/test_activity_logger.py::test_logs",
    )

    assert lane_for_item(item, _ROOT, _CONFIG) is (
        explain_lane_for_item(item, _ROOT, _CONFIG).lane
    )


def test_explanation_text_lists_each_test_with_lane_and_rule() -> None:
    postgres = LaneSpec(name="postgres", marker="postgres_integration")
    other = LaneSpec(name="other", marker="unit", classifier_fallback=True)
    entries = [
        (
            "db/test_users.py::test_insert",
            LaneAssignment(
                lane=postgres,
                rule_kind="classifier_path_prefixes",
                matched_value="db/",
            ),
        ),
        (
            "test_math.py::test_add",
            LaneAssignment(
                lane=other, rule_kind="classifier_fallback", matched_value=""
            ),
        ),
    ]

    text = format_lane_explanation(entries)

    assert (
        "db/test_users.py::test_insert -> postgres (classifier_path_prefixes: db/)"
        in text
    )
    assert "test_math.py::test_add -> other (classifier_fallback)" in text
    assert "2 tests in 2 lanes" in text
