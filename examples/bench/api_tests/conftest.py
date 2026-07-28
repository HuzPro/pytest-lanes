"""Simulated per-process environment spin-up for this lane."""

import pytest

from _burn import burn


@pytest.fixture(scope="session", autouse=True)
def simulated_environment():
    burn(3.0)
    yield
