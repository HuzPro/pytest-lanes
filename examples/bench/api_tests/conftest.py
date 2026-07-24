"""Simulated per-process environment spin-up for this lane.

A session-scoped autouse fixture sleeping 3.0s stands in for booting a
container/daemon. Every *process* that runs tests from this directory pays
it once — a lane child pays it once, each lane shard pays it again, and
every xdist worker that touches this directory pays its own copy. That is
exactly the fixed-cost profile the modes differ on.
"""

import time

import pytest


@pytest.fixture(scope="session", autouse=True)
def simulated_environment():
    time.sleep(3.0)
    yield
