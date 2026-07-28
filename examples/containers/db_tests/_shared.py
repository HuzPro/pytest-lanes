"""Shared per-process infrastructure for the db lane."""

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
        # The postgres image restarts during first-boot init; verify each attempt with a real round trip.
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
