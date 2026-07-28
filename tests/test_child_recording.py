"""Behavioral tests for the child-side run recorder."""

from __future__ import annotations

import json
from pathlib import Path

from pytest_lanes.recording import ChildRunRecorder


def _recorder_with_scripted_clock(
    tmp_path: Path, times: list[float]
) -> ChildRunRecorder:
    ticks = iter(times)
    return ChildRunRecorder(
        output_path=tmp_path / "lane.json", clock=lambda: next(ticks)
    )


def test_recorder_measures_collect_startup_and_total(tmp_path: Path) -> None:
    # t=10 start, t=11 collected, t=17 first test (6s spin-up), t=40 end.
    recorder = _recorder_with_scripted_clock(tmp_path, [10.0, 11.0, 17.0, 40.0])

    recorder.mark_session_start()
    recorder.mark_collection_finished()
    recorder.mark_test_started()
    recorder.write()

    written = json.loads((tmp_path / "lane.json").read_text(encoding="utf-8"))
    assert written["collect"] == 1.0
    assert written["startup"] == 6.0
    assert written["total"] == 30.0


def test_recorder_sums_report_durations_per_file(tmp_path: Path) -> None:
    recorder = _recorder_with_scripted_clock(tmp_path, [0.0, 0.1, 0.2, 9.0])
    recorder.mark_session_start()
    recorder.mark_collection_finished()
    recorder.mark_test_started()

    recorder.add_report_duration("db/test_users.py::test_a", 1.5)
    recorder.add_report_duration("db/test_users.py::test_b", 2.0)
    recorder.add_report_duration("db/test_orders.py::test_c", 3.0)
    recorder.write()

    written = json.loads((tmp_path / "lane.json").read_text(encoding="utf-8"))
    assert written["files"] == {"db/test_users.py": 3.5, "db/test_orders.py": 3.0}


def test_only_the_first_test_start_defines_startup(tmp_path: Path) -> None:
    recorder = _recorder_with_scripted_clock(tmp_path, [0.0, 1.0, 5.0, 30.0, 60.0])
    recorder.mark_session_start()
    recorder.mark_collection_finished()
    recorder.mark_test_started()
    recorder.mark_test_started()
    recorder.write()

    written = json.loads((tmp_path / "lane.json").read_text(encoding="utf-8"))
    assert written["startup"] == 4.0


def test_recorder_writes_zero_costs_when_no_tests_ran(tmp_path: Path) -> None:
    recorder = _recorder_with_scripted_clock(tmp_path, [0.0, 0.5, 2.0])
    recorder.mark_session_start()
    recorder.mark_collection_finished()
    recorder.write()

    written = json.loads((tmp_path / "lane.json").read_text(encoding="utf-8"))
    assert written["startup"] == 0.0
    assert written["collect"] == 0.5
    assert written["files"] == {}
