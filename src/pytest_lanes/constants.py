"""Process-level constants for lane orchestration.

These are *not* lane definitions (those live in the host project's INI file
and are loaded via :mod:`pytest_lanes.config`). They are runtime constants the
plugin needs to communicate with child pytest subprocesses and pace its main
loop.
"""

from __future__ import annotations

TEST_ORCHESTRATION_CHILD_ENV = "PYTEST_LANES_CHILD"
SHOW_LANE_OUTPUT_ENV = "PYTEST_LANES_SHOW_OUTPUT"

LANE_POLL_INTERVAL_SECONDS = 0.05
