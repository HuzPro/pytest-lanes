"""End-to-end tests: a real ``pytest`` invocation fans out into lane subprocesses."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from importlib.util import find_spec
from pathlib import Path
from xml.etree import ElementTree

import pytest

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
    # UTF-8 child output so the rich table renders on legacy consoles.
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


_PROJECT_PYPROJECT = """\
[tool.pytest.ini_options]
markers = [
    "io: simulated infrastructure-heavy tests",
    "unit: fast unit tests",
]

[tool.pytest-lanes]
lanes = ["io", "other"]
subprocess_order_standard = ["io", "other"]

[tool.pytest-lanes.lane.io]
marker = "io"
classifier_path_prefixes = ["io_tests/"]
subprocess_paths = ["io_tests"]

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_fallback = true
subprocess_ignore_other_lanes = true
"""


def test_project_configured_only_via_pyproject_toml_fans_out(tmp_path: Path) -> None:
    # No INI file anywhere: [tool.pytest-lanes] is the whole configuration.
    (tmp_path / "pyproject.toml").write_text(_PROJECT_PYPROJECT, encoding="utf-8")
    _write_test_directories(tmp_path)

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


def test_junit_report_holds_every_lanes_tests(tmp_path: Path) -> None:
    # Given a CI-style run asking for one JUnit report across lanes.
    _write_demo_project(tmp_path)
    report = tmp_path / "report.xml"

    result = _run_pytest_in(tmp_path, extra_args=(f"--junitxml={report}",))

    assert result.returncode == 0, result.stdout + result.stderr
    document = ElementTree.parse(report).getroot()
    recorded = {case.get("name") for case in document.iter("testcase")}
    assert recorded == {"test_io_lane_runs", "test_unit_lane_runs"}
    # A consumer that reads only the root element must see the true total.
    assert int(document.get("tests", "0")) == len(recorded)


@pytest.mark.skipif(
    find_spec("pytest_cov") is None, reason="requires pytest-cov installed"
)
def test_coverage_run_completes_and_combines_lane_data(tmp_path: Path) -> None:
    # Given --cov, children must not share one .coverage SQLite file.
    _write_demo_project(tmp_path)

    result = _run_pytest_in(tmp_path, extra_args=("--cov=.", "--cov-report="))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "DataError" not in result.stdout
    assert "FAIL" not in result.stdout
    assert (tmp_path / ".coverage").exists(), "combined coverage data missing"


@pytest.mark.skipif(
    find_spec("pytest_cov") is None, reason="requires pytest-cov installed"
)
def test_coverage_xml_report_is_written_once_for_the_whole_run(
    tmp_path: Path,
) -> None:
    # The parent produces the report after combining; children stay silent.
    _write_demo_project(tmp_path)
    coverage_xml = tmp_path / "cov.xml"

    result = _run_pytest_in(
        tmp_path, extra_args=("--cov=.", f"--cov-report=xml:{coverage_xml}")
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert coverage_xml.exists(), "requested coverage xml was never written"
    measured = ElementTree.parse(coverage_xml).getroot()
    filenames = {element.get("filename", "") for element in measured.iter("class")} | {
        element.get("name", "") for element in measured.iter("class")
    }
    flattened = " ".join(sorted(filenames))
    # Both module names appearing proves the data was combined.
    assert "test_io.py" in flattened, flattened
    assert "test_unit.py" in flattened, flattened


def test_lanes_beyond_max_workers_wait_for_a_free_slot(tmp_path: Path) -> None:
    _write_demo_project(tmp_path, extra_index_lines="max_workers = 1\n")
    # One worker, declared order io -> other, makes the sentinel deterministic.
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


def test_orchestrated_run_records_lane_durations_for_the_next_run(
    tmp_path: Path,
) -> None:
    _write_demo_project(tmp_path)

    result = _run_pytest_in(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    durations_file = (
        tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "lane_durations.json"
    )
    assert durations_file.exists()
    recorded = json.loads(durations_file.read_text(encoding="utf-8"))
    assert set(recorded) == {"io", "other"}
    assert all(entry["total"] > 0 for entry in recorded.values())
    assert "io_tests/test_io.py" in recorded["io"]["files"]
    assert recorded["io"]["files"]["io_tests/test_io.py"] > 0
    assert recorded["io"]["collect"] > 0


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


_DIVISIBLE_LANE_INI = """\
[pytest]
markers =
\tio: simulated infrastructure-heavy tests
\tunit: fast unit tests

[pytest-lanes]
lanes = io other
subprocess_order_standard = io other

[pytest-lanes:io]
marker = io
classifier_path_prefixes = io_tests/
subprocess_paths = io_tests
divisible = files

[pytest-lanes:other]
marker = unit
classifier_fallback = true
subprocess_ignore_other_lanes = true
"""


def test_recorded_divisible_lane_shards_in_a_real_run(tmp_path: Path) -> None:
    from pytest_lanes.durations import LaneRecord, duration_store_for_rootdir

    (tmp_path / "pytest.ini").write_text(_DIVISIBLE_LANE_INI, encoding="utf-8")
    io_dir = tmp_path / "io_tests"
    io_dir.mkdir()
    file_records = []
    for index in range(4):
        name = f"test_io_{index}.py"
        (io_dir / name).write_text(
            f"def test_io_{index}():\n    assert True\n", encoding="utf-8"
        )
        file_records.append((f"io_tests/{name}", 9.5))
    unit_dir = tmp_path / "unit_tests"
    unit_dir.mkdir()
    (unit_dir / "test_unit.py").write_text(
        "def test_unit_lane_runs():\n    assert True\n", encoding="utf-8"
    )
    # Seed durations that make the split clearly profitable.
    duration_store_for_rootdir(tmp_path).record(
        {
            "io": LaneRecord(
                total=40.0, startup=1.0, collect=1.0, files=tuple(file_records)
            ),
            "other": LaneRecord(total=4.0),
        }
    )

    result = _run_pytest_in(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "sharded io into 2" in result.stdout
    assert "io~1of2" in result.stdout
    assert "io~2of2" in result.stdout
    assert "FAIL" not in result.stdout
    assert (
        tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "shard_plan.json"
    ).exists()


_XDIST_LANE_INI = """\
[pytest]
markers =
\tio: simulated infrastructure-heavy tests
\tunit: fast unit tests

[pytest-lanes]
lanes = io other
subprocess_order_standard = io other

[pytest-lanes:io]
marker = io
classifier_path_prefixes = io_tests/
subprocess_paths = io_tests
lane_numprocesses = 2

[pytest-lanes:other]
marker = unit
classifier_fallback = true
subprocess_ignore_other_lanes = true
"""


def test_lane_numprocesses_runs_that_lane_under_xdist(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text(_XDIST_LANE_INI, encoding="utf-8")
    io_dir = tmp_path / "io_tests"
    io_dir.mkdir()
    for index in range(2):
        (io_dir / f"test_io_{index}.py").write_text(
            f"def test_io_{index}():\n    assert True\n", encoding="utf-8"
        )
    unit_dir = tmp_path / "unit_tests"
    unit_dir.mkdir()
    (unit_dir / "test_unit.py").write_text(
        "def test_unit_lane_runs():\n    assert True\n", encoding="utf-8"
    )

    result = _run_pytest_in(tmp_path)

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lane Test Summary" in result.stdout
    assert "FAIL" not in result.stdout
    # The xdist controller receives every worker's reports.
    durations_file = (
        tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "lane_durations.json"
    )
    recorded = json.loads(durations_file.read_text(encoding="utf-8"))
    assert "io_tests/test_io_0.py" in recorded["io"]["files"]


def test_lanes_suggest_prints_reviewable_ini_for_an_unconfigured_project(
    tmp_path: Path,
) -> None:
    _write_test_directories(tmp_path)

    result = _run_pytest_in(tmp_path, extra_args=("--lanes-suggest",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "[pytest-lanes:io_tests]" in result.stdout
    assert "[pytest-lanes:unit_tests]" in result.stdout
    assert "--lanes-explain" in result.stdout
    # Only prints the suggestion; no tests execute.
    assert "Lane Test Summary" not in result.stdout


def test_lanes_auto_orchestrates_by_directory_layout(tmp_path: Path) -> None:
    _write_test_directories(tmp_path)

    result = _run_pytest_in(tmp_path, extra_args=("--lanes-auto",))

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Lane Test Summary" in result.stdout
    assert "io_tests" in result.stdout
    assert "unit_tests" in result.stdout
    assert "FAIL" not in result.stdout
