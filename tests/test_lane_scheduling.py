"""Behavioral tests for the bounded lane scheduler."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from pytest_lanes import executor
from pytest_lanes.lanes import LaneCommand
from pytest_lanes.reporter import LaneProgressReporter
from pytest_lanes.scheduler import (
    DeclaredOrderPolicy,
    LaneWorkQueue,
    LongestFirstPolicy,
    detected_cpu_count,
    ordering_policy_for,
    resolve_max_workers,
)


def _commands(*names: str) -> list[LaneCommand]:
    return [LaneCommand(name=name, args=(".",)) for name in names]


def test_ready_lanes_are_capped_by_max_workers() -> None:
    work_queue = LaneWorkQueue(
        commands=_commands("postgres", "redis", "other"),
        max_workers=2,
        policy=DeclaredOrderPolicy(),
    )

    ready = work_queue.ready_to_launch()

    assert [command.name for command in ready] == ["postgres", "redis"]


def test_finishing_a_lane_releases_a_slot_for_the_next_pending_lane() -> None:
    work_queue = LaneWorkQueue(
        commands=_commands("postgres", "redis", "other"),
        max_workers=2,
        policy=DeclaredOrderPolicy(),
    )
    for command in work_queue.ready_to_launch():
        work_queue.mark_launched(command.name)

    assert work_queue.ready_to_launch() == ()

    work_queue.mark_finished("postgres")

    assert [command.name for command in work_queue.ready_to_launch()] == ["other"]


def test_max_workers_at_or_above_lane_count_launches_everything_at_once() -> None:
    work_queue = LaneWorkQueue(
        commands=_commands("postgres", "redis", "other"),
        max_workers=8,
        policy=DeclaredOrderPolicy(),
    )

    ready = work_queue.ready_to_launch()

    assert [command.name for command in ready] == ["postgres", "redis", "other"]


def test_queue_is_done_only_after_every_lane_finishes() -> None:
    work_queue = LaneWorkQueue(
        commands=_commands("postgres", "other"),
        max_workers=2,
        policy=DeclaredOrderPolicy(),
    )
    for command in work_queue.ready_to_launch():
        work_queue.mark_launched(command.name)

    work_queue.mark_finished("postgres")
    assert not work_queue.is_done()

    work_queue.mark_finished("other")
    assert work_queue.is_done()


def test_cli_max_workers_overrides_ini_which_overrides_detected_cpu_count() -> None:
    assert resolve_max_workers(cli_value=3, config_value=5, detected=8) == 3
    assert resolve_max_workers(cli_value=None, config_value=5, detected=8) == 5
    assert resolve_max_workers(cli_value=None, config_value=None, detected=8) == 8


def test_non_positive_max_workers_is_rejected() -> None:
    with pytest.raises(pytest.UsageError, match="positive"):
        resolve_max_workers(cli_value=0, config_value=None, detected=8)


def test_detected_cpu_count_reports_at_least_one_core() -> None:
    with patch("os.cpu_count", return_value=None):
        assert detected_cpu_count() == 1


def test_longest_first_policy_orders_known_lanes_by_recorded_duration() -> None:
    policy = LongestFirstPolicy({"fast": 2.0, "slow": 30.0, "mid": 10.0})

    ordered = policy.ordered(_commands("fast", "mid", "slow"))

    assert [command.name for command in ordered] == ["slow", "mid", "fast"]


def test_longest_first_policy_launches_unrecorded_lanes_first() -> None:
    policy = LongestFirstPolicy({"known": 5.0})

    ordered = policy.ordered(_commands("known", "new_a", "new_b"))

    # An unmeasured lane may be the longest; start it early.
    assert [command.name for command in ordered] == ["new_a", "new_b", "known"]


def test_ordering_policy_is_longest_first_only_when_data_exists() -> None:
    assert isinstance(ordering_policy_for({}), DeclaredOrderPolicy)
    assert isinstance(ordering_policy_for({"db": 1.0}), LongestFirstPolicy)


class _FakeProcess:
    def __init__(self, exit_code: int) -> None:
        self._exit_code = exit_code

    def poll(self) -> int:
        return self._exit_code


def test_tolerant_lane_treats_no_tests_collected_exit_as_success() -> None:
    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    run = executor._LaneRun(
        name="other", process=_FakeProcess(5), tolerate_no_tests=True
    )
    work_queue = LaneWorkQueue(
        commands=_commands("other"), max_workers=1, policy=DeclaredOrderPolicy()
    )
    work_queue.mark_launched("other")

    executor._record_finished_lanes([run], reporter, work_queue)

    assert run.exit_code == 0
    assert reporter.lane_results()[0]["exit_code"] == 0


def test_intolerant_lane_keeps_no_tests_collected_as_a_failure() -> None:
    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["db"])
    reporter.mark_started("db")
    run = executor._LaneRun(name="db", process=_FakeProcess(5), tolerate_no_tests=False)
    work_queue = LaneWorkQueue(
        commands=_commands("db"), max_workers=1, policy=DeclaredOrderPolicy()
    )
    work_queue.mark_launched("db")

    executor._record_finished_lanes([run], reporter, work_queue)

    assert run.exit_code == 5
