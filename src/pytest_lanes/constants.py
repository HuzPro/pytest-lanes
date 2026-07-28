"""Process-level constants for lane orchestration."""

from __future__ import annotations

TEST_ORCHESTRATION_CHILD_ENV = "PYTEST_LANES_CHILD"
CHILD_DURATIONS_OUT_ENV = "PYTEST_LANES_DURATIONS_OUT"
SHOW_LANE_OUTPUT_ENV = "PYTEST_LANES_SHOW_OUTPUT"
# Set by pytest-xdist in its worker processes; we never record there.
XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"

LANE_POLL_INTERVAL_SECONDS = 0.05
