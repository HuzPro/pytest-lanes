"""Behavioral tests for per-lane JUnit XML redirection and merging.

Every lane child receives the user's passthrough argv, so a single
``--junitxml=report.xml`` makes every lane write the same file and the last
writer wins. These tests pin the two halves of the fix: redirecting each
lane to its own staging path, and merging the staged documents back into one
report whose root totals are correct.
"""

from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree

import pytest

from pytest_lanes.report_merge import (
    JunitMergeError,
    args_with_lane_junit_path,
    junit_target_path,
    lane_junit_path,
    merged_junit_document,
)


def _lane_document(
    name: str = "pytest",
    tests: int = 1,
    failures: int = 0,
    errors: int = 0,
    skipped: int = 0,
    time: float = 1.0,
    cases: str = '<testcase classname="tests.test_one" name="test_first" time="1.0" />',
) -> str:
    return (
        "<?xml version='1.0' encoding='utf-8'?>\n"
        "<testsuites>"
        f'<testsuite name="{name}" errors="{errors}" failures="{failures}" '
        f'skipped="{skipped}" tests="{tests}" time="{time}" '
        'timestamp="2026-07-25T12:00:00.000000" hostname="ci">'
        f"{cases}"
        "</testsuite></testsuites>"
    )


def test_junit_target_path_is_absent_when_no_junit_flag_was_passed() -> None:
    assert junit_target_path(("-q", "tests/")) is None


def test_junit_target_path_reads_the_value_joined_by_equals() -> None:
    assert junit_target_path(("-q", "--junitxml=build/report.xml")) == (
        "build/report.xml"
    )


def test_junit_target_path_reads_the_value_from_the_following_token() -> None:
    assert junit_target_path(("--junitxml", "build/report.xml", "-q")) == (
        "build/report.xml"
    )


def test_junit_target_path_accepts_the_hyphenated_junit_xml_spelling() -> None:
    assert junit_target_path(("--junit-xml=report.xml",)) == "report.xml"


def test_lane_junit_path_stages_one_xml_file_per_lane(tmp_path: Path) -> None:
    staged = lane_junit_path("postgres", tmp_path)

    assert staged.parent == tmp_path
    assert staged.name == "postgres.xml"


def test_lane_junit_path_replaces_characters_shard_names_carry(tmp_path: Path) -> None:
    staged = lane_junit_path("postgres~1of2", tmp_path)

    assert staged.name == "postgres_1of2.xml"


def test_lane_args_pass_through_untouched_when_no_report_was_requested(
    tmp_path: Path,
) -> None:
    args = ("-q", "--maxfail=1", "tests/")

    assert args_with_lane_junit_path(args, "postgres", tmp_path) == args


def test_lane_args_redirect_the_requested_report_to_the_lane_staging_path(
    tmp_path: Path,
) -> None:
    redirected = args_with_lane_junit_path(
        ("-q", "--junitxml=report.xml"), "postgres", tmp_path
    )

    staged = lane_junit_path("postgres", tmp_path)
    assert redirected == ("-q", f"--junitxml={staged}")


def test_lane_args_collapse_the_two_token_form_into_a_single_token(
    tmp_path: Path,
) -> None:
    redirected = args_with_lane_junit_path(
        ("--junit-xml", "report.xml", "-q"), "postgres", tmp_path
    )

    staged = lane_junit_path("postgres", tmp_path)
    assert redirected == (f"--junit-xml={staged}", "-q")


def test_lane_args_redirect_every_occurrence_of_a_repeated_flag(
    tmp_path: Path,
) -> None:
    """A user path left behind on any occurrence is the data loss returning."""
    redirected = args_with_lane_junit_path(
        ("--junitxml=first.xml", "--junitxml=second.xml"), "postgres", tmp_path
    )

    staged = lane_junit_path("postgres", tmp_path)
    assert redirected == (f"--junitxml={staged}", f"--junitxml={staged}")


def test_merging_no_documents_yields_an_empty_but_valid_report() -> None:
    merged = merged_junit_document(())

    root = ElementTree.fromstring(merged)
    assert root.tag == "testsuites"
    assert root.get("tests") == "0"
    assert list(root) == []


def test_merged_report_sums_every_lanes_counts_onto_the_root() -> None:
    merged = merged_junit_document(
        (
            _lane_document(tests=3, failures=1, errors=0, skipped=1),
            _lane_document(tests=2, failures=0, errors=1, skipped=0),
        )
    )

    root = ElementTree.fromstring(merged)
    assert root.get("tests") == "5"
    assert root.get("failures") == "1"
    assert root.get("errors") == "1"
    assert root.get("skipped") == "1"


def test_merged_report_sums_lane_durations_at_three_decimals() -> None:
    merged = merged_junit_document(
        (_lane_document(time=1.5), _lane_document(time=2.25))
    )

    assert ElementTree.fromstring(merged).get("time") == "3.750"


def test_merged_report_keeps_the_test_cases_of_every_lane() -> None:
    merged = merged_junit_document(
        (
            _lane_document(cases='<testcase classname="a" name="test_a" />'),
            _lane_document(cases='<testcase classname="b" name="test_b" />'),
        )
    )

    root = ElementTree.fromstring(merged)
    case_names = [case.get("name") for case in root.iter("testcase")]
    assert case_names == ["test_a", "test_b"]


def test_merged_report_disambiguates_suites_that_share_a_name() -> None:
    merged = merged_junit_document((_lane_document(), _lane_document()))

    root = ElementTree.fromstring(merged)
    assert [suite.get("name") for suite in root] == ["pytest-1", "pytest-2"]


def test_merged_report_leaves_an_already_distinct_suite_name_alone() -> None:
    merged = merged_junit_document(
        (_lane_document(name="postgres"), _lane_document(name="timescale"))
    )

    root = ElementTree.fromstring(merged)
    assert [suite.get("name") for suite in root] == ["postgres", "timescale"]


def test_merge_skips_a_lane_that_never_wrote_its_report() -> None:
    merged = merged_junit_document((_lane_document(tests=2), "", "   \n"))

    root = ElementTree.fromstring(merged)
    assert root.get("tests") == "2"
    assert len(list(root)) == 1


def test_merge_raises_when_a_staged_report_is_not_valid_xml() -> None:
    with pytest.raises(JunitMergeError, match="valid XML"):
        merged_junit_document((_lane_document(), "<testsuite><testcase></testsuite>"))


def test_merge_raises_when_a_staged_report_has_an_unexpected_root() -> None:
    with pytest.raises(JunitMergeError, match="testsuites"):
        merged_junit_document(("<coverage line-rate='1.0' />",))


def test_merge_accepts_a_document_whose_root_is_a_bare_testsuite() -> None:
    bare = (
        '<testsuite name="pytest" errors="0" failures="0" skipped="0" tests="2" '
        'time="0.5"><testcase classname="a" name="test_a" /></testsuite>'
    )

    root = ElementTree.fromstring(merged_junit_document((bare,)))

    assert root.tag == "testsuites"
    assert root.get("tests") == "2"
    assert [case.get("name") for case in root.iter("testcase")] == ["test_a"]


def test_merging_the_same_documents_twice_produces_identical_text() -> None:
    documents = (_lane_document(tests=2), _lane_document(tests=3))

    assert merged_junit_document(documents) == merged_junit_document(documents)
