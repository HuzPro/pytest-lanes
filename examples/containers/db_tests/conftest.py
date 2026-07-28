"""Every db module holds the fixed daemon port for its whole duration."""

from __future__ import annotations

import socket

import pytest

from db_tests._shared import FIXED_PORT


@pytest.fixture(scope="module", autouse=True)
def daemon_port():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", FIXED_PORT))
    sock.listen(1)
    yield
    sock.close()
