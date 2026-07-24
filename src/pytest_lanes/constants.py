"""Process-level constants for lane orchestration.

These are *not* lane definitions (those live in the host project's INI file
and are loaded via :mod:`pytest_lanes.config`). They are runtime constants the
plugin needs to communicate with child pytest subprocesses and pace its main
loop.
"""

from __future__ import annotations

TEST_ORCHESTRATION_CHILD_ENV = "PYTEST_LANES_CHILD"
CHILD_DURATIONS_OUT_ENV = "PYTEST_LANES_DURATIONS_OUT"
SHOW_LANE_OUTPUT_ENV = "PYTEST_LANES_SHOW_OUTPUT"
# Set by pytest-xdist in its worker processes; we never record there.
XDIST_WORKER_ENV = "PYTEST_XDIST_WORKER"

LANE_POLL_INTERVAL_SECONDS = 0.05
