"""Behavioral tests for per-lane coverage data files and parent-side reports.

Every lane child inherits the user's ``--cov`` argv, so all of them write the
same ``.coverage`` SQLite file and coverage.py dies with ``no such table:
other_db.file`` - reported as a lane failure even when every test passed.
These tests pin the fix: one data file per lane, measurement left on in the
children, and report generation deferred to the parent after combining.
"""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.coverage_support import (
    COVERAGE_DATA_ENV,
    args_without_coverage_reports,
    coverage_report_command,
    is_coverage_requested,
    lane_coverage_env,
    requested_coverage_reports,
)


def test_coverage_is_not_requested_when_no_cov_argument_was_passed() -> None:
    assert is_coverage_requested(("-q", "tests/")) is False


def test_coverage_is_requested_by_a_bare_cov_flag() -> None:
    assert is_coverage_requested(("-q", "--cov")) is True


def test_coverage_is_requested_when_a_package_is_named() -> None:
    assert is_coverage_requested(("--cov=pytest_lanes",)) is True


def test_coverage_is_requested_by_any_cov_prefixed_option() -> None:
    assert is_coverage_requested(("--cov-report=term-missing",)) is True
    assert is_coverage_requested(("--cov-append",)) is True


def test_an_unrelated_option_that_merely_starts_like_cov_is_not_coverage() -> None:
    """Prefix matching alone would claim any future ``--cov...`` spelling."""
    assert is_coverage_requested(("--covfefe",)) is False


def test_each_lane_is_pointed_at_its_own_coverage_data_file(tmp_path: Path) -> None:
    environment = lane_coverage_env("postgres", tmp_path)

    assert len(environment) == 1
    name, value = environment[0]
    assert name == COVERAGE_DATA_ENV
    assert Path(value).parent == tmp_path


def test_lane_data_file_is_named_for_coverage_combine_to_discover(
    tmp_path: Path,
) -> None:
    """``coverage combine`` finds sibling data by the ``.coverage.`` prefix."""
    _, value = lane_coverage_env("postgres", tmp_path)[0]

    assert Path(value).name == ".coverage.postgres"


def test_lane_data_file_replaces_characters_shard_names_carry(tmp_path: Path) -> None:
    _, value = lane_coverage_env("postgres~1of2", tmp_path)[0]

    assert Path(value).name == ".coverage.postgres_1of2"


def test_lane_args_are_untouched_when_no_report_was_requested() -> None:
    args = ("-q", "--cov=pytest_lanes", "tests/")

    assert args_without_coverage_reports(args) == args


def test_lane_args_drop_a_report_request_joined_by_equals() -> None:
    stripped = args_without_coverage_reports(
        ("-q", "--cov=pytest_lanes", "--cov-report=term-missing")
    )

    assert stripped == ("-q", "--cov=pytest_lanes")


def test_lane_args_drop_a_report_request_and_the_value_token_after_it() -> None:
    stripped = args_without_coverage_reports(
        ("--cov-report", "xml:cov.xml", "--cov=pytest_lanes")
    )

    assert stripped == ("--cov=pytest_lanes",)


def test_lane_args_keep_measurement_and_every_other_coverage_option() -> None:
    """Children must still measure - only reporting moves to the parent."""
    stripped = args_without_coverage_reports(
        ("--cov=pytest_lanes", "--cov-branch", "--cov-report=html", "-p", "no:randomly")
    )

    assert stripped == ("--cov=pytest_lanes", "--cov-branch", "-p", "no:randomly")


def test_no_reports_are_requested_when_the_user_asked_for_none() -> None:
    assert requested_coverage_reports(("--cov=pytest_lanes",)) == ()


def test_requested_reports_are_listed_in_the_order_the_user_gave_them() -> None:
    requested = requested_coverage_reports(
        (
            "--cov-report=term-missing",
            "--cov=pytest_lanes",
            "--cov-report",
            "xml:cov.xml",
        )
    )

    assert requested == ("term-missing", "xml:cov.xml")


def test_a_terminal_report_maps_to_the_plain_coverage_report_command() -> None:
    assert coverage_report_command("term") == ("report",)


def test_a_report_spec_left_empty_still_maps_to_a_terminal_report() -> None:
    assert coverage_report_command("") == ("report",)


def test_a_terminal_report_can_ask_for_the_uncovered_lines() -> None:
    assert coverage_report_command("term-missing") == ("report", "--show-missing")


def test_a_file_report_without_a_destination_leaves_the_default_in_place() -> None:
    assert coverage_report_command("xml") == ("xml",)
    assert coverage_report_command("json") == ("json",)
    assert coverage_report_command("lcov") == ("lcov",)
    assert coverage_report_command("html") == ("html",)
    assert coverage_report_command("annotate") == ("annotate",)


def test_a_file_report_with_a_destination_names_the_output_file() -> None:
    assert coverage_report_command("xml:build/cov.xml") == (
        "xml",
        "-o",
        "build/cov.xml",
    )
    assert coverage_report_command("json:cov.json") == ("json", "-o", "cov.json")
    assert coverage_report_command("lcov:cov.info") == ("lcov", "-o", "cov.info")


def test_a_directory_report_with_a_destination_names_the_output_directory() -> None:
    """``coverage html`` writes a tree, so its destination flag differs."""
    assert coverage_report_command("html:build/htmlcov") == (
        "html",
        "-d",
        "build/htmlcov",
    )


def test_an_unrecognized_report_spec_maps_to_no_command_at_all() -> None:
    assert coverage_report_command("teamcity") is None


def test_a_recognized_report_with_an_unmodellable_modifier_maps_to_no_command() -> None:
    """Guessing at a modifier would report something other than was asked."""
    assert coverage_report_command("term-missing:skip-covered") is None
