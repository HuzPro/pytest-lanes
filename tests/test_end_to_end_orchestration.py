"""End-to-end tests: a real ``pytest`` invocation fans out into lane subprocesses.

Each test generates a miniature two-lane project in ``tmp_path``, runs
``python -m pytest .`` there with the installed plugin, and asserts on the
user-observable outcome: lanes execute, exit codes propagate, and the lane
summary is printed. These tests require the package to be installed in the
current environment (``pip install -e .``).
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV

_PROJECT_INI = """\
[pytest]
markers =
\tio: simulated infrastructure-heavy tests
\tunit: fast unit tests

[pytest-lanes]
lanes = io other
subprocess_order_standard = io other
{extra_index_lines}
[pytest-lanes:io]
marker = io
classifier_path_prefixes = io_tests/
subprocess_paths = io_tests

[pytest-lanes:other]
marker = unit
classifier_fallback = true
subprocess_ignore_other_lanes = true
"""


def _write_test_directories(root: Path) -> None:
    io_dir = root / "io_tests"
    io_dir.mkdir()
    (io_dir / "test_io.py").write_text(
        "def test_io_lane_runs():\n    assert True\n", encoding="utf-8"
    )
    unit_dir = root / "unit_tests"
    unit_dir.mkdir()
    (unit_dir / "test_unit.py").write_text(
        "def test_unit_lane_runs():\n    assert True\n", encoding="utf-8"
    )


def _write_demo_project(root: Path, extra_index_lines: str = "") -> None:
    ini_body = _PROJECT_INI.format(extra_index_lines=extra_index_lines)
    (root / "pytest.ini").write_text(ini_body, encoding="utf-8")
    _write_test_directories(root)


def _run_pytest_in(
    root: Path, extra_args: tuple[str, ...] = ()
) -> subprocess.CompletedProcess[str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key != TEST_ORCHESTRATION_CHILD_ENV
    }
    # Keep child output UTF-8 so the rich table renders identically on
    # Windows runners with legacy console encodings.
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(
        [sys.executable, "-m", "pytest", ".", *extra_args],
        cwd=root,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=300,
        check=False,
    )


def test_pytest_run_fans_out_into_one_subprocess_per_lane(tmp_path: Path) -> None:
    _write_demo_project(tmp_path)

    result = _run_pytest_in(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lane Test Summary" in result.stdout
    assert "io" in result.stdout
    assert "other" in result.stdout
    assert "FAIL" not in result.stdout


def test_failing_lane_propagates_exit_code_and_surfaces_its_output(
    tmp_path: Path,
) -> None:
    _write_demo_project(tmp_path)
    (tmp_path / "unit_tests" / "test_failing.py").write_text(
        "def test_broken():\n    assert False\n", encoding="utf-8"
    )

    result = _run_pytest_in(tmp_path)

    assert result.returncode != 0
    assert "test_broken" in result.stdout
    assert "Lane Test Summary" in result.stdout


def test_lanes_beyond_max_workers_wait_for_a_free_slot(tmp_path: Path) -> None:
    _write_demo_project(tmp_path, extra_index_lines="max_workers = 1\n")
    # The io lane finishes by writing a sentinel; the other lane's test only
    # passes if that sentinel already exists when it runs. With one worker
    # and declared order io -> other, this is deterministic — no timing
    # assertions needed.
    (tmp_path / "io_tests" / "test_io.py").write_text(
        "import time\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def test_io_lane_writes_sentinel_before_finishing():\n"
        "    time.sleep(1.0)\n"
        "    sentinel = Path(__file__).resolve().parent.parent / 'io_done.txt'\n"
        "    sentinel.write_text('done', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (tmp_path / "unit_tests" / "test_unit.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def test_other_lane_launches_only_after_io_lane_finished():\n"
        "    sentinel = Path(__file__).resolve().parent.parent / 'io_done.txt'\n"
        "    assert sentinel.exists()\n",
        encoding="utf-8",
    )

    result = _run_pytest_in(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "FAIL" not in result.stdout


def test_lanes_explain_lists_each_test_with_lane_and_rule_without_running(
    tmp_path: Path,
) -> None:
    _write_demo_project(tmp_path)
    # A test that fails loudly if executed: --lanes-explain must only collect.
    (tmp_path / "io_tests" / "test_io.py").write_text(
        "def test_io_lane_runs():\n"
        "    raise AssertionError('must not execute under --lanes-explain')\n",
        encoding="utf-8",
    )

    result = _run_pytest_in(tmp_path, extra_args=("--lanes-explain",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert (
        "io_tests/test_io.py::test_io_lane_runs -> io "
        "(classifier_path_prefixes: io_tests/)"
    ) in result.stdout
    assert (
        "unit_tests/test_unit.py::test_unit_lane_runs -> other (classifier_fallback)"
    ) in result.stdout
    assert "2 tests in 2 lanes" in result.stdout


def test_lane_defs_orchestrate_without_any_config_file(tmp_path: Path) -> None:
    _write_test_directories(tmp_path)

    result = _run_pytest_in(
        tmp_path,
        extra_args=("--lane-def", "io=io_tests", "--lane-def", "units=unit_tests"),
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lane Test Summary" in result.stdout
    assert "io" in result.stdout
    assert "units" in result.stdout
    assert "FAIL" not in result.stdout


def test_lanes_auto_orchestrates_by_directory_layout(tmp_path: Path) -> None:
    _write_test_directories(tmp_path)

    result = _run_pytest_in(tmp_path, extra_args=("--lanes-auto",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lane Test Summary" in result.stdout
    assert "io_tests" in result.stdout
    assert "unit_tests" in result.stdout
    assert "FAIL" not in result.stdout
