"""Persistence of per-lane run measurements across orchestrated runs."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

_CACHE_RELATIVE_PATH = Path(".pytest_cache") / "v" / "pytest-lanes"
_DURATIONS_FILENAME = "lane_durations.json"


@dataclass(frozen=True)
class LaneRecord:
    total: float
    startup: float = 0.0
    collect: float = 0.0
    files: tuple[tuple[str, float], ...] = ()

    def files_as_dict(self) -> dict[str, float]:
        return dict(self.files)


class DurationStore(Protocol):
    def recorded_durations(self) -> dict[str, float]: ...

    def recorded_lane_records(self) -> dict[str, LaneRecord]: ...

    def record(self, records: Mapping[str, LaneRecord]) -> None: ...


class InMemoryDurationStore:
    """Test double and null-object: keeps records for this process only."""

    def __init__(self, initial: Mapping[str, LaneRecord] | None = None) -> None:
        self._records: dict[str, LaneRecord] = dict(initial or {})

    def recorded_durations(self) -> dict[str, float]:
        return {name: record.total for name, record in self._records.items()}

    def recorded_lane_records(self) -> dict[str, LaneRecord]:
        return dict(self._records)

    def record(self, records: Mapping[str, LaneRecord]) -> None:
        self._records.update(records)


class JsonFileDurationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def recorded_durations(self) -> dict[str, float]:
        return {
            name: record.total for name, record in self.recorded_lane_records().items()
        }

    def recorded_lane_records(self) -> dict[str, LaneRecord]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}

        records: dict[str, LaneRecord] = {}
        for name, value in raw.items():
            record = _lane_record_from_json(value)
            if record is not None:
                records[str(name)] = record
        return records

    def record(self, records: Mapping[str, LaneRecord]) -> None:
        merged = self.recorded_lane_records()
        merged.update(records)
        payload = {
            name: {**asdict(record), "files": record.files_as_dict()}
            for name, record in merged.items()
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _lane_record_from_json(value: object) -> LaneRecord | None:
    # v1 schema: the value is the lane's total seconds as a bare number.
    if isinstance(value, (int, float)):
        return LaneRecord(total=float(value))

    if not isinstance(value, dict):
        return None
    total = value.get("total")
    if not isinstance(total, (int, float)):
        return None

    raw_files = value.get("files")
    files = (
        tuple(
            (str(path), float(seconds))
            for path, seconds in raw_files.items()
            if isinstance(seconds, (int, float))
        )
        if isinstance(raw_files, dict)
        else ()
    )
    return LaneRecord(
        total=float(total),
        startup=_float_or_zero(value.get("startup")),
        collect=_float_or_zero(value.get("collect")),
        files=files,
    )


def _float_or_zero(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def duration_store_for_rootdir(rootpath: Path) -> JsonFileDurationStore:
    return JsonFileDurationStore(rootpath / _CACHE_RELATIVE_PATH / _DURATIONS_FILENAME)
