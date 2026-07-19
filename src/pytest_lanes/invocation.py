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
    positional_args = [arg for arg in invocation_args_value if is_positional_arg(arg)]
    if not positional_args:
        return False

    for arg in positional_args:
        if arg == ".":
            continue
        return True

    return False


def passthrough_args_for_lanes(invocation_args_value: tuple[str, ...]) -> tuple[str, ...]:
    passthrough: list[str] = []
    for arg in invocation_args_value:
        if arg == ".":
            continue
        passthrough.append(arg)
    return tuple(passthrough)
