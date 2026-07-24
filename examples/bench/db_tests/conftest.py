"""Simulated per-process environment spin-up for this lane.

A session-scoped autouse fixture burning 6.0 units of CPU stands in
for booting a container/daemon. Every *process* that runs tests from this
directory pays it once — a lane child pays it once, each lane shard pays
it again, and every xdist worker that touches this directory pays its own
copy, in real compute that contends with the tests themselves.
"""

import pytest

from _burn import burn


@pytest.fixture(scope="session", autouse=True)
def simulated_environment():
    burn(6.0)
    yield
