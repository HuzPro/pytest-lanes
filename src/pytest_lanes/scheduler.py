"""Bounded scheduling of lane subprocesses.

The executor asks a :class:`LaneWorkQueue` which lanes may launch right now:
at most ``max_workers`` lanes run concurrently, and pending lanes launch in
the order chosen by a :class:`LaneOrderingPolicy` as running lanes finish.

``DeclaredOrderPolicy`` preserves the configured ``subprocess_order_*``
order. A duration-aware longest-first policy is planned once recorded lane
durations exist to draw on.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping, Sequence
from typing import Protocol

import pytest

from pytest_lanes.lanes import LaneCommand


def detected_cpu_count() -> int:
    return os.cpu_count() or 1


def resolve_max_workers(
    cli_value: int | None, config_value: int | None, detected: int
) -> int:
    resolved = next(
        (value for value in (cli_value, config_value) if value is not None), detected
    )
    if resolved <= 0:
        raise pytest.UsageError(
            f"max workers must be a positive integer (got {resolved})."
        )
    return resolved


class LaneOrderingPolicy(Protocol):
    """Strategy choosing the launch order of pending lanes."""

    def ordered(self, commands: Sequence[LaneCommand]) -> tuple[LaneCommand, ...]: ...


class DeclaredOrderPolicy:
    """Launch lanes exactly in their declared configuration order."""

    def ordered(self, commands: Sequence[LaneCommand]) -> tuple[LaneCommand, ...]:
        return tuple(commands)


class LongestFirstPolicy:
    """Queue lanes with the longest recorded duration first.

    Lanes with no recorded duration launch before recorded ones, keeping
    their declared relative order — an unmeasured lane may be the longest,
    and starting it early is the safe scheduling bet.
    """

    def __init__(self, recorded_durations: Mapping[str, float]) -> None:
        self._recorded = dict(recorded_durations)

    def ordered(self, commands: Sequence[LaneCommand]) -> tuple[LaneCommand, ...]:
        return tuple(
            sorted(
                commands,
                key=lambda command: self._recorded.get(command.name, math.inf),
                reverse=True,
            )
        )


def ordering_policy_for(
    recorded_durations: Mapping[str, float],
) -> LaneOrderingPolicy:
    if recorded_durations:
        return LongestFirstPolicy(recorded_durations)
    return DeclaredOrderPolicy()


class LaneWorkQueue:
    """Tracks which lanes are pending, running, and finished under a worker cap."""

    def __init__(
        self,
        commands: Sequence[LaneCommand],
        max_workers: int,
        policy: LaneOrderingPolicy,
    ) -> None:
        self._pending: list[LaneCommand] = list(policy.ordered(commands))
        self._max_workers = max_workers
        self._running: set[str] = set()
        self._finished: set[str] = set()
        self._total_count = len(self._pending)

    def ready_to_launch(self) -> tuple[LaneCommand, ...]:
        free_slots = max(self._max_workers - len(self._running), 0)
        return tuple(self._pending[:free_slots])

    def mark_launched(self, lane_name: str) -> None:
        self._pending = [
            command for command in self._pending if command.name != lane_name
        ]
        self._running.add(lane_name)

    def mark_finished(self, lane_name: str) -> None:
        self._running.discard(lane_name)
        self._finished.add(lane_name)

    def is_done(self) -> bool:
        return len(self._finished) == self._total_count
