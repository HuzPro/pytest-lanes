"""Persistence of per-lane run measurements across orchestrated runs."""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from pytest_lanes.constants import CACHE_RELATIVE_PATH

_DURATIONS_FILENAME = "lane_durations.json"

FileDurations = Iterable[tuple[str, float]]


def total_seconds(files: FileDurations) -> float:
    """The summed duration of a ``(path, seconds)`` collection."""
    return sum(seconds for _, seconds in files)


def contiguous_halves(
    files: tuple[tuple[str, float], ...],
) -> tuple[tuple[tuple[str, float], ...], tuple[tuple[str, float], ...]]:
    """Cut the file list at the point that best balances the two halves."""
    total = total_seconds(files)
    best_cut = 1
    best_imbalance = float("inf")
    running = 0.0
    for index, (_, seconds) in enumerate(files[:-1], start=1):
        running += seconds
        imbalance = abs(running - (total - running))
        if imbalance < best_imbalance:
            best_imbalance = imbalance
            best_cut = index
    return files[:best_cut], files[best_cut:]


def json_dict_or_empty(path: Path) -> dict[str, object]:
    """The JSON object at ``path``, or empty when absent or unreadable."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def write_json_file(path: Path, payload: object, indent: int | None = 2) -> None:
    """Write ``payload`` as JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=indent), encoding="utf-8")


def float_or_zero(value: object) -> float:
    return float(value) if isinstance(value, (int, float)) else 0.0


def file_seconds_from_json(raw: object) -> tuple[tuple[str, float], ...]:
    """Coerce a decoded ``{path: seconds}`` mapping to the recorded-file shape."""
    if not isinstance(raw, dict):
        return ()
    return tuple(
        (str(path), float(seconds))
        for path, seconds in raw.items()
        if isinstance(seconds, (int, float))
    )


@dataclass(frozen=True)
class LaneRecord:
    total: float
    startup: float = 0.0
    collect: float = 0.0
    files: tuple[tuple[str, float], ...] = ()

    def files_as_dict(self) -> dict[str, float]:
        return dict(self.files)

    @property
    def files_seconds(self) -> float:
        return total_seconds(self.files)

    def as_payload(self) -> dict[str, object]:
        """The JSON shape both the child sidecar and the store are written in."""
        return {**asdict(self), "files": self.files_as_dict()}


def lane_record_from_file(path: Path) -> LaneRecord:
    """One lane's recorded measurements, zeroed when the file is absent."""
    return _lane_record_from_json(json_dict_or_empty(path)) or LaneRecord(total=0.0)


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
        records: dict[str, LaneRecord] = {}
        for name, value in json_dict_or_empty(self._path).items():
            record = _lane_record_from_json(value)
            if record is not None:
                records[str(name)] = record
        return records

    def record(self, records: Mapping[str, LaneRecord]) -> None:
        merged = self.recorded_lane_records()
        merged.update(records)
        payload = {name: record.as_payload() for name, record in merged.items()}
        write_json_file(self._path, payload)


def _lane_record_from_json(value: object) -> LaneRecord | None:
    # v1 schema: the value is the lane's total seconds as a bare number.
    if isinstance(value, (int, float)):
        return LaneRecord(total=float(value))

    if not isinstance(value, dict):
        return None
    total = value.get("total")
    if not isinstance(total, (int, float)):
        return None

    return LaneRecord(
        total=float(total),
        startup=float_or_zero(value.get("startup")),
        collect=float_or_zero(value.get("collect")),
        files=file_seconds_from_json(value.get("files")),
    )


def duration_store_for_rootdir(rootpath: Path) -> JsonFileDurationStore:
    return JsonFileDurationStore(rootpath / CACHE_RELATIVE_PATH / _DURATIONS_FILENAME)
