"""Process-level constants and leaf helpers for lane orchestration."""

from __future__ import annotations

import os
import re
from pathlib import Path

TEST_ORCHESTRATION_CHILD_ENV = "PYTEST_LANES_CHILD"
CHILD_DURATIONS_OUT_ENV = "PYTEST_LANES_DURATIONS_OUT"
SHOW_LANE_OUTPUT_ENV = "PYTEST_LANES_SHOW_OUTPUT"
# Set by pytest-xdist in its worker processes; we never record there.
XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"

ENV_ENABLED = "1"

CACHE_RELATIVE_PATH = Path(".pytest_cache") / "v" / "pytest-lanes"

LANE_POLL_INTERVAL_SECONDS = 0.05

_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")
_UNNAMED_LANE = "lane"


def lane_filename_token(lane_name: str) -> str:
    """Reduce a lane name to something safe to put in a filename."""
    token = _UNSAFE_IN_FILENAME.sub("_", lane_name).strip("_")
    return token or _UNNAMED_LANE


def env_flag_enabled(name: str) -> bool:
    return os.environ.get(name) == ENV_ENABLED


def is_lane_child() -> bool:
    return env_flag_enabled(TEST_ORCHESTRATION_CHILD_ENV)
