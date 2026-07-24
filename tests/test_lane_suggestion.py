"""Behavioral tests for ``--lanes-suggest`` static project scanning.

The suggester reads structure only — directory layout, conftest.py ASTs
(scoped fixtures, infrastructure imports) — and prints a commented
``[pytest-lanes]`` INI block framed as a suggestion to review, never an
oracle. No user code is executed.
"""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.suggest import format_lane_suggestion, scan_project

_CONFTEST_WITH_INFRA = """\
import pytest
from testcontainers.postgres import PostgresContainer
import psycopg


@pytest.fixture(scope="session")
def pg_container():
    yield


@pytest.fixture
def per_test_helper():
    yield
"""


def _write_test_file(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "test_sample.py").write_text(
        "def test_ok():\n    assert True\n", encoding="utf-8"
    )


def test_scan_captures_infrastructure_imports_and_scoped_fixtures(
    tmp_path: Path,
) -> None:
    _write_test_file(tmp_path / "db_tests")
    (tmp_path / "db_tests" / "conftest.py").write_text(
        _CONFTEST_WITH_INFRA, encoding="utf-8"
    )
    _write_test_file(tmp_path / "unit_tests")

    scan = scan_project(tmp_path)

    by_name = {directory.name: directory for directory in scan.directories}
    assert "testcontainers" in by_name["db_tests"].infrastructure_imports
    assert "psycopg" in by_name["db_tests"].infrastructure_imports
    assert by_name["db_tests"].scoped_fixtures == ("pg_container",)
    assert by_name["unit_tests"].infrastructure_imports == ()
    assert by_name["unit_tests"].scoped_fixtures == ()


def test_suggestion_orders_infrastructure_heavy_lanes_first(tmp_path: Path) -> None:
    _write_test_file(tmp_path / "api_tests")
    _write_test_file(tmp_path / "db_tests")
    (tmp_path / "db_tests" / "conftest.py").write_text(
        _CONFTEST_WITH_INFRA, encoding="utf-8"
    )

    suggestion = format_lane_suggestion(scan_project(tmp_path))

    assert "lanes = db_tests api_tests other" in suggestion
    # No root-level stray tests in this layout: scheduling the empty
    # fallback would fail the run, so it must stay out of the order list.
    assert "subprocess_order_standard = db_tests api_tests\n" in suggestion


def test_root_level_tests_schedule_the_fallback_in_the_suggestion(
    tmp_path: Path,
) -> None:
    _write_test_file(tmp_path / "api_tests")
    _write_test_file(tmp_path / "db_tests")
    (tmp_path / "db_tests" / "conftest.py").write_text(
        _CONFTEST_WITH_INFRA, encoding="utf-8"
    )
    (tmp_path / "test_stray.py").write_text(
        "def test_stray():\n    assert True\n", encoding="utf-8"
    )

    suggestion = format_lane_suggestion(scan_project(tmp_path))

    assert "subprocess_order_standard = db_tests api_tests other" in suggestion


def test_suggestion_is_a_reviewable_ini_block_with_fallback_and_markers(
    tmp_path: Path,
) -> None:
    _write_test_file(tmp_path / "db_tests")
    (tmp_path / "db_tests" / "conftest.py").write_text(
        _CONFTEST_WITH_INFRA, encoding="utf-8"
    )
    _write_test_file(tmp_path / "unit_tests")

    suggestion = format_lane_suggestion(scan_project(tmp_path))

    assert "[pytest-lanes:db_tests]" in suggestion
    assert "classifier_path_prefixes = db_tests/" in suggestion
    assert "testcontainers" in suggestion
    assert "[pytest-lanes:other]" in suggestion
    assert "classifier_fallback = true" in suggestion
    assert "markers =" in suggestion
    assert "--lanes-explain" in suggestion


def test_suggestion_without_a_partition_says_so_instead_of_guessing(
    tmp_path: Path,
) -> None:
    _write_test_file(tmp_path / "only_dir")

    suggestion = format_lane_suggestion(scan_project(tmp_path))

    assert "no test-bearing subdirectory partition" in suggestion
    assert "[pytest-lanes]" not in suggestion
