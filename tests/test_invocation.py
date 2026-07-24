"""Behavioral tests for argv inspection around the zero-config flags.

``--lane-def db=tests/db`` may arrive as two argv tokens; the value token
looks positional but must be treated as the flag's value everywhere argv is
inspected — otherwise orchestration would wrongly step aside, and lane
children would receive definition tokens as collection targets.
"""

from __future__ import annotations

from pytest_lanes.invocation import has_targeted_paths, passthrough_args_for_lanes


def test_split_lane_def_value_is_not_a_targeted_path() -> None:
    assert has_targeted_paths(("--lane-def", "db=tests/db", ".")) is False


def test_passthrough_strips_lane_def_pairs_and_inline_forms() -> None:
    args = (".", "--lane-def", "db=tests/db", "--lane-def=api=tests/api", "-q")

    assert passthrough_args_for_lanes(args) == ("-q",)


def test_passthrough_strips_the_lanes_auto_flag() -> None:
    assert passthrough_args_for_lanes((".", "--lanes-auto", "-q")) == ("-q",)
