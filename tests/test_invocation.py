"""Behavioral tests for argv inspection around the zero-config flags."""

from __future__ import annotations

import pytest

from pytest_lanes.invocation import (
    has_custom_selection,
    has_targeted_paths,
    passthrough_args_for_lanes,
    wants_live_lane_output,
)


def test_split_lane_def_value_is_not_a_targeted_path() -> None:
    assert has_targeted_paths(("--lane-def", "db=tests/db", ".")) is False


@pytest.mark.parametrize(
    "argument",
    ["-k", "-m", "-kcheckout", "-mslow", "--lane", "--lane=db", "--lf", "--ff"],
)
def test_selection_arguments_are_a_custom_selection(argument: str) -> None:
    assert has_custom_selection((".", argument)) is True


@pytest.mark.parametrize(
    "argument",
    ["--lanes-full", "--lanes-auto", "--lanes-suggest", "--lanes-no-shard"],
)
def test_lanes_own_flags_are_not_a_custom_selection(argument: str) -> None:
    assert has_custom_selection((".", argument)) is False


@pytest.mark.parametrize(
    "argument",
    ["-s", "--capture=no", "--capture", "-sv", "-xs"],
)
def test_disabling_capture_asks_for_live_lane_output(argument: str) -> None:
    # Given -s: output must stream live, not only on failure.
    assert wants_live_lane_output((".", argument)) is True


@pytest.mark.parametrize(
    "argument",
    ["-q", "--capture=fd", "--capture=sys", "-x", "--co", "--strict-markers"],
)
def test_ordinary_arguments_leave_lane_output_captured(argument: str) -> None:
    # Given no live-output request, output stays folded into the summary.
    assert wants_live_lane_output((".", argument)) is False


def test_passthrough_strips_lane_def_pairs_and_inline_forms() -> None:
    args = (".", "--lane-def", "db=tests/db", "--lane-def=api=tests/api", "-q")

    assert passthrough_args_for_lanes(args) == ("-q",)


def test_passthrough_strips_the_lanes_auto_flag() -> None:
    assert passthrough_args_for_lanes((".", "--lanes-auto", "-q")) == ("-q",)
