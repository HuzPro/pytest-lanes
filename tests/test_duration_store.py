"""Behavioral tests for per-lane duration persistence.

Recorded wall times from one orchestrated run feed the next run's
longest-first scheduling and pending-lane ETAs. The JSON store lives under
pytest's cache directory and must degrade gracefully: a missing or corrupt
file simply means no recorded data yet.
"""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.durations import JsonFileDurationStore, duration_store_for_rootdir


def _store(tmp_path: Path) -> JsonFileDurationStore:
    return JsonFileDurationStore(tmp_path / "lane_durations.json")


def test_recording_then_reading_round_trips(tmp_path: Path) -> None:
    store = _store(tmp_path)

    store.record({"postgres": 31.8, "other": 30.9})

    assert store.recorded_durations() == {"postgres": 31.8, "other": 30.9}


def test_missing_file_reads_as_no_recorded_durations(tmp_path: Path) -> None:
    assert _store(tmp_path).recorded_durations() == {}


def test_corrupt_file_reads_as_no_recorded_durations(tmp_path: Path) -> None:
    path = tmp_path / "lane_durations.json"
    path.write_text("{not json", encoding="utf-8")

    assert JsonFileDurationStore(path).recorded_durations() == {}


def test_recording_merges_with_previously_recorded_lanes(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.record({"postgres": 30.0, "timescale": 16.0})

    store.record({"postgres": 32.0, "acceptance": 1.1})

    assert store.recorded_durations() == {
        "postgres": 32.0,
        "timescale": 16.0,
        "acceptance": 1.1,
    }


def test_store_for_rootdir_lives_under_the_pytest_cache(tmp_path: Path) -> None:
    store = duration_store_for_rootdir(tmp_path)

    store.record({"db": 4.2})

    expected = tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "lane_durations.json"
    assert expected.exists()
