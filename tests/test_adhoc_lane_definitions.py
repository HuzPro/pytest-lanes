"""Behavioral tests for ``--lane-def`` ad-hoc lane construction."""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_lanes.adhoc import (
    lane_config_from_definitions,
    resolve_lane_config_or_none,
)
from pytest_lanes.lane_selection import apply_lane_filter
from pytest_lanes.lanes import build_lane_commands

_INI_WITH_LANES = """\
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = ini_lane
subprocess_order_standard = ini_lane

[pytest-lanes:ini_lane]
marker = unit
classifier_fallback = true
"""


def test_single_definition_builds_that_lane_plus_a_fallback() -> None:
    config = lane_config_from_definitions(("db=tests/integration",))

    db = config.lane_by_name("db")
    assert db is not None
    assert db.classifier_path_prefixes == ("tests/integration",)
    assert db.subprocess_paths == ("tests/integration",)
    assert db.marker == ""

    fallback = config.fallback_lane()
    assert fallback is not None
    assert fallback.name == "other"
    assert fallback.subprocess_ignore_other_lanes is True
    assert config.subprocess_order_standard == ("db", "other")


def test_definitions_keep_their_order_and_split_comma_separated_paths() -> None:
    config = lane_config_from_definitions(
        ("db=tests/integration", "api=tests/api,tests/contracts")
    )

    api = config.lane_by_name("api")
    assert api is not None
    assert api.classifier_path_prefixes == ("tests/api", "tests/contracts")
    assert api.subprocess_paths == ("tests/api", "tests/contracts")
    assert config.subprocess_order_standard == ("db", "api", "other")


def test_fallback_lane_tolerates_collecting_no_tests() -> None:
    config = lane_config_from_definitions(("db=tests/integration",))

    fallback = config.fallback_lane()
    assert fallback is not None
    assert fallback.tolerate_no_tests is True


def test_definition_without_equals_is_rejected() -> None:
    with pytest.raises(pytest.UsageError, match="name=path"):
        lane_config_from_definitions(("tests/integration",))


def test_definition_using_the_reserved_fallback_name_is_rejected() -> None:
    with pytest.raises(pytest.UsageError, match="reserved"):
        lane_config_from_definitions(("other=tests/misc",))


def test_duplicate_definition_names_are_rejected() -> None:
    with pytest.raises(pytest.UsageError, match="db"):
        lane_config_from_definitions(("db=tests/integration", "db=tests/api"))


class _RecordingItem:
    def __init__(self, path: Path, nodeid: str) -> None:
        self.path = path
        self.nodeid = nodeid
        self.cls = None
        self.markers: list[object] = []

    def add_marker(self, marker: object) -> None:
        self.markers.append(marker)


def test_adhoc_lanes_apply_no_markers_to_their_items() -> None:
    config = lane_config_from_definitions(("db=tests/integration",))
    item = _RecordingItem(
        path=Path("C:/repo/tests/integration/test_db.py"),
        nodeid="tests/integration/test_db.py::test_insert",
    )

    apply_lane_filter(
        items=[item],
        rootpath=Path("C:/repo"),
        lane_config=config,
        selected_lanes=(),
        marker_factory=lambda name: f"marker:{name}",
    )

    assert item.markers == []


def test_built_commands_carry_the_fallback_tolerance() -> None:
    config = lane_config_from_definitions(("db=tests/db",))

    commands = build_lane_commands(
        mode="standard", passthrough_args=(), lane_config=config
    )

    by_name = {command.name: command for command in commands}
    assert by_name["other"].tolerate_no_tests is True
    assert by_name["db"].tolerate_no_tests is False


def test_cli_definitions_win_over_ini_config(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text(_INI_WITH_LANES, encoding="utf-8")

    config = resolve_lane_config_or_none(
        cli_definitions=("db=tests/db",), lanes_auto=False, rootpath=tmp_path
    )

    assert config is not None
    assert config.lane_by_name("db") is not None
    assert config.lane_by_name("ini_lane") is None


def test_auto_partition_is_used_when_no_definitions_are_passed(
    tmp_path: Path,
) -> None:
    for directory in ("db_tests", "unit_tests"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "test_sample.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8"
        )

    config = resolve_lane_config_or_none(
        cli_definitions=(), lanes_auto=True, rootpath=tmp_path
    )

    assert config is not None
    assert config.lane_by_name("db_tests") is not None


def test_ini_config_is_used_when_no_zero_config_flags_are_passed(
    tmp_path: Path,
) -> None:
    (tmp_path / "pytest.ini").write_text(_INI_WITH_LANES, encoding="utf-8")

    config = resolve_lane_config_or_none(
        cli_definitions=(), lanes_auto=False, rootpath=tmp_path
    )

    assert config is not None
    assert config.lane_by_name("ini_lane") is not None


def test_nothing_configured_resolves_to_none_and_stays_dormant(
    tmp_path: Path,
) -> None:
    resolved = resolve_lane_config_or_none(
        cli_definitions=(), lanes_auto=False, rootpath=tmp_path
    )

    assert resolved is None
