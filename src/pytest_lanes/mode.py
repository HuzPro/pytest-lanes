"""Mode selection for lane orchestration."""

from __future__ import annotations

from typing import Protocol

from pytest_lanes.constants import is_lane_child
from pytest_lanes.invocation import (
    SupportsInvocationParams,
    has_custom_selection,
    has_targeted_paths,
    invocation_args,
)


class LaneModeConfig(SupportsInvocationParams, Protocol):
    """The part of a pytest config that mode selection reads."""

    def getoption(self, name: str) -> object: ...


def _option_enabled(config: LaneModeConfig, option_name: str) -> bool:
    getoption = getattr(config, "getoption", None)
    if getoption is None:
        return False

    try:
        return bool(getoption(option_name))
    except (TypeError, ValueError):
        return False


def orchestration_mode(config: LaneModeConfig) -> str | None:
    if is_lane_child():
        return None

    invocation_args_value = invocation_args(config)
    if has_custom_selection(invocation_args_value):
        return None
    if has_targeted_paths(invocation_args_value):
        return None

    if _option_enabled(config, "--lanes-explain"):
        return None

    if _option_enabled(config, "--lanes-full"):
        return "full"
    return "standard"
