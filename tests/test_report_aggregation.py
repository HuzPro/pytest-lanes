"""Behavioral tests for per-lane report staging."""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.lanes import LaneCommand
from pytest_lanes.report_aggregation import prepare_lane_reports


def _commands(*args: str) -> list[LaneCommand]:
    return [
        LaneCommand(name="io", args=tuple(args)),
        LaneCommand(name="other", args=tuple(args)),
    ]


def test_lanes_without_report_arguments_are_left_untouched(tmp_path: Path) -> None:
    # Arrange
    commands = _commands("-q", "io_tests")

    # Act
    prepared, plan = prepare_lane_reports(commands, staging_dir=tmp_path)

    # Assert: nothing to aggregate, nothing to rewrite.
    assert [command.args for command in prepared] == [
        command.args for command in commands
    ]
    assert plan.junit_target is None
    assert plan.coverage_requested is False


def test_each_lane_writes_its_junit_report_to_its_own_staging_path(
    tmp_path: Path,
) -> None:
    # Arrange
    commands = _commands("-q", "--junitxml=report.xml")

    # Act
    prepared, plan = prepare_lane_reports(commands, staging_dir=tmp_path)

    # Assert: the user's path is remembered once, and no two lanes share a path.
    assert plan.junit_target == "report.xml"
    written = [
        argument
        for command in prepared
        for argument in command.args
        if argument.startswith("--junitxml=")
    ]
    assert len(written) == len(commands)
    assert len(set(written)) == len(commands)
    assert all("report.xml" not in argument for argument in written)


def test_each_lane_measures_coverage_into_its_own_data_file(tmp_path: Path) -> None:
    # Arrange
    commands = _commands("-q", "--cov=pkg")

    # Act
    prepared, plan = prepare_lane_reports(commands, staging_dir=tmp_path)

    # Assert: measurement survives, into per-lane data files.
    assert plan.coverage_requested is True
    assert all("--cov=pkg" in command.args for command in prepared)
    data_files = [dict(command.env_set)["COVERAGE_FILE"] for command in prepared]
    assert len(set(data_files)) == len(commands)


def test_child_lanes_do_not_emit_their_own_partial_coverage_reports(
    tmp_path: Path,
) -> None:
    # Arrange
    commands = _commands("-q", "--cov=pkg", "--cov-report=xml:cov.xml")

    # Act
    prepared, plan = prepare_lane_reports(commands, staging_dir=tmp_path)

    # Assert: request remembered for the parent; children silenced.
    assert plan.coverage_reports == ("xml:cov.xml",)
    for command in prepared:
        assert "--cov-report=xml:cov.xml" not in command.args
        assert "--cov-report=" in command.args


def test_explicitly_disabled_coverage_report_is_not_resurrected(
    tmp_path: Path,
) -> None:
    # Arrange: `--cov-report=` means "measure, report nothing".
    commands = _commands("-q", "--cov=pkg", "--cov-report=")

    # Act
    _, plan = prepare_lane_reports(commands, staging_dir=tmp_path)

    # Assert
    assert plan.coverage_requested is True
    assert plan.coverage_reports == ()
