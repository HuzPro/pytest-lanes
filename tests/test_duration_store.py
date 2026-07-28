"""Behavioral tests for per-lane duration persistence (v2 schema)."""

from __future__ import annotations

import json
from pathlib import Path

from pytest_lanes.durations import (
    JsonFileDurationStore,
    LaneRecord,
    duration_store_for_rootdir,
)


def _store(tmp_path: Path) -> JsonFileDurationStore:
    return JsonFileDurationStore(tmp_path / "lane_durations.json")


def test_recording_then_reading_round_trips_full_lane_records(tmp_path: Path) -> None:
    store = _store(tmp_path)
    record = LaneRecord(
        total=31.8,
        startup=6.2,
        collect=0.8,
        files=(("db/test_users.py", 12.0), ("db/test_orders.py", 12.8)),
    )

    store.record({"postgres": record})

    assert store.recorded_lane_records() == {"postgres": record}


def test_recorded_durations_exposes_lane_totals_for_scheduling(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record(
        {
            "postgres": LaneRecord(total=31.8, startup=6.2),
            "other": LaneRecord(total=30.9),
        }
    )

    assert store.recorded_durations() == {"postgres": 31.8, "other": 30.9}


def test_missing_file_reads_as_no_recorded_durations(tmp_path: Path) -> None:
    assert _store(tmp_path).recorded_lane_records() == {}


def test_corrupt_file_reads_as_no_recorded_durations(tmp_path: Path) -> None:
    path = tmp_path / "lane_durations.json"
    path.write_text("{not json", encoding="utf-8")

    assert JsonFileDurationStore(path).recorded_lane_records() == {}


def test_v1_flat_files_migrate_as_totals_only(tmp_path: Path) -> None:
    path = tmp_path / "lane_durations.json"
    path.write_text(json.dumps({"postgres": 31.8}), encoding="utf-8")
    store = JsonFileDurationStore(path)

    records = store.recorded_lane_records()

    assert records["postgres"].total == 31.8
    assert records["postgres"].files == ()
    assert store.recorded_durations() == {"postgres": 31.8}


def test_recording_merges_lanes_but_replaces_each_lane_record_wholesale(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    store.record(
        {
            "postgres": LaneRecord(total=30.0, files=(("a.py", 30.0),)),
            "redis": LaneRecord(total=16.0),
        }
    )

    store.record({"postgres": LaneRecord(total=32.0, files=(("b.py", 32.0),))})

    records = store.recorded_lane_records()
    assert records["postgres"] == LaneRecord(total=32.0, files=(("b.py", 32.0),))
    assert records["redis"] == LaneRecord(total=16.0)


def test_store_for_rootdir_lives_under_the_pytest_cache(tmp_path: Path) -> None:
    store = duration_store_for_rootdir(tmp_path)

    store.record({"db": LaneRecord(total=4.2)})

    expected = tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "lane_durations.json"
    assert expected.exists()
