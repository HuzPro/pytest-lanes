"""Invocation parsing helpers for pytest orchestration decisions."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Protocol


class SupportsInvocationParams(Protocol):
    """The part of a pytest config that reports the argv it was invoked with."""

    @property
    def invocation_params(self) -> _InvocationParams: ...


class _InvocationParams(Protocol):
    @property
    def args(self) -> Sequence[str]: ...


SELECTION_FLAGS = frozenset(
    {
        "-k",
        "-m",
        "--lf",
        "--ff",
        "--last-failed",
        "--failed-first",
    }
)

_SELECTION_PREFIXES = ("-k", "-m", "--lane=")

# Uncaptured output streams live instead of folding into the summary.
_CAPTURE_DISABLING_ARGS = frozenset({"-s", "--capture=no", "--capture"})
_SHORT_OPTION_CLUSTER = re.compile(r"^-[a-zA-Z]+$")
_CAPTURE_DISABLING_SHORT_OPTION = "s"


def invocation_args(config: SupportsInvocationParams) -> tuple[str, ...]:
    invocation_params = getattr(config, "invocation_params", None)
    if invocation_params is None:
        return ()

    args = getattr(invocation_params, "args", ())
    return tuple(str(arg) for arg in args)


def is_positional_arg(arg: str) -> bool:
    return not arg.startswith("-")


def has_custom_selection(invocation_args_value: tuple[str, ...]) -> bool:
    return any(
        arg in SELECTION_FLAGS or arg == "--lane" or arg.startswith(_SELECTION_PREFIXES)
        for arg in invocation_args_value
    )


def wants_live_lane_output(invocation_args_value: tuple[str, ...]) -> bool:
    """Did the caller disable capture, i.e. ask to see output as it happens?"""
    for arg in invocation_args_value:
        if arg in _CAPTURE_DISABLING_ARGS:
            return True
        if _SHORT_OPTION_CLUSTER.match(arg) and (
            _CAPTURE_DISABLING_SHORT_OPTION in arg
        ):
            return True
    return False


def has_targeted_paths(invocation_args_value: tuple[str, ...]) -> bool:
    for arg in _args_without_lane_def_values(invocation_args_value):
        if is_positional_arg(arg) and arg != ".":
            return True
    return False


def passthrough_args_for_lanes(
    invocation_args_value: tuple[str, ...],
) -> tuple[str, ...]:
    passthrough: list[str] = []
    for arg in _args_without_lane_def_values(invocation_args_value):
        if arg == ".":
            continue
        if arg.startswith("--lane-def=") or arg == "--lanes-auto":
            continue
        passthrough.append(arg)
    return tuple(passthrough)


def _args_without_lane_def_values(
    invocation_args_value: tuple[str, ...],
) -> tuple[str, ...]:
    """Drop the value token following each bare ``--lane-def`` flag."""
    remaining: list[str] = []
    skip_next = False
    for arg in invocation_args_value:
        if skip_next:
            skip_next = False
            continue
        if arg == "--lane-def":
            skip_next = True
            continue
        remaining.append(arg)
    return tuple(remaining)
