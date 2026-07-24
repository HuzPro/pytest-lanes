"""Invocation parsing helpers for pytest orchestration decisions.

The plugin needs to inspect the raw argv pytest was called with to decide
whether to fan out into lane subprocesses or behave as plain pytest. A user
who passes ``-k something`` or ``--lane=postgres`` or a concrete path is
expressing a custom selection — orchestration steps aside in those cases so
their request flows through to a single pytest invocation.
"""

from __future__ import annotations

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


def invocation_args(config: object) -> tuple[str, ...]:
    invocation_params = getattr(config, "invocation_params", None)
    if invocation_params is None:
        return ()

    args = getattr(invocation_params, "args", ())
    return tuple(str(arg) for arg in args)


def is_positional_arg(arg: str) -> bool:
    return not arg.startswith("-")


def has_custom_selection(invocation_args_value: tuple[str, ...]) -> bool:
    for arg in invocation_args_value:
        if arg in SELECTION_FLAGS:
            return True
        if arg.startswith("-k") and arg != "-k":
            return True
        if arg.startswith("-m") and arg != "-m":
            return True
        if arg == "--lane" or arg.startswith("--lane="):
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
    """Drop the value token following each bare ``--lane-def`` flag.

    ``--lane-def db=tests/db`` arrives as two argv tokens; the second looks
    positional but is the flag's value, not a collection target.
    """
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
