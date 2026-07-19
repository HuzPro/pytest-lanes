"""Shared per-process infrastructure for the db lane.

``SinglePostgres`` mimics the common real-world pattern of a session-singleton
container: started once per process, reused by every db test module. Under
test-level distribution (pytest-xdist), every worker process that touches a
db test starts its own copy of this container.

``FIXED_PORT`` simulates a daemon that owns one well-known port — the kind of
process-global resource that collides when tests sharing it are scheduled
onto different workers at the same time.
"""

from __future__ import annotations

import time

import psycopg
from testcontainers.postgres import PostgresContainer

FIXED_PORT = 53555


class SinglePostgres:
    _conn: psycopg.Connection | None = None

    @classmethod
    def connection(cls) -> psycopg.Connection:
        if cls._conn is None:
            container = PostgresContainer("postgres:16-alpine")
            container.start()
            url = container.get_connection_url()
            for sqlalchemy_prefix in ("postgresql+psycopg2://", "postgresql+psycopg://"):
                url = url.replace(sqlalchemy_prefix, "postgresql://")
            cls._conn = cls._connect_verified(url)
        return cls._conn

    @staticmethod
    def _connect_verified(url: str, attempts: int = 10) -> psycopg.Connection:
        # The stock postgres image restarts once during first-boot init; a
        # connection that lands in that window dies on first use, so verify
        # each attempt with a real round trip.
        last_error: psycopg.OperationalError | None = None
        for _ in range(attempts):
            try:
                conn = psycopg.connect(url, autocommit=True)
                conn.execute("SELECT 1")
                return conn
            except psycopg.OperationalError as error:
                last_error = error
                time.sleep(0.5)
        raise last_error
