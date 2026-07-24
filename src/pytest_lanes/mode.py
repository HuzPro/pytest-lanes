"""Mode selection for lane orchestration.

Returns one of ``"full"``, ``"standard"``, or ``None``:

* ``"full"`` — fan out into every lane, including those declared as ``optional``.
* ``"standard"`` — fan out into the standard lane set only.
* ``None`` — do not orchestrate; let pytest run as a single invocation. Used
  when this process is itself a child lane subprocess (detected via env var),
  when the user passed a custom selection (``-k``, ``-m``, ``--lane=``),
  when the user pointed at specific paths instead of ``.``, or when
  ``--lanes-explain`` asks for the classification listing instead of a run.
"""

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
