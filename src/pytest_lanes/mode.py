"""Mode selection for lane orchestration."""

from __future__ import annotations

import os

from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV
from pytest_lanes.invocation import (
    has_custom_selection,
    has_targeted_paths,
    invocation_args,
)


def _option_enabled(config: object, option_name: str) -> bool:
    getoption = getattr(config, "getoption", None)
    if getoption is None:
        return False

    try:
        return bool(getoption(option_name))
    except (TypeError, ValueError):
        return False


def orchestration_mode(config: object) -> str | None:
    if os.environ.get(TEST_ORCHESTRATION_CHILD_ENV) == "1":
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
