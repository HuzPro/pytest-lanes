"""Persistence of per-lane wall-clock durations across orchestrated runs.

Recorded durations feed longest-first lane ordering and pending-lane ETAs.
``JsonFileDurationStore`` is the on-disk adapter; it stores a flat
``{lane_name: seconds}`` JSON object under pytest's cache directory
(``.pytest_cache/v/pytest-lanes/``) so the artifact lives where pytest
users already expect ephemeral cross-run state. A missing or corrupt file
degrades to "no recorded data" — never an error.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Protocol

_CACHE_RELATIVE_PATH = Path(".pytest_cache") / "v" / "pytest-lanes"
_DURATIONS_FILENAME = "lane_durations.json"


class DurationStore(Protocol):
    def recorded_durations(self) -> dict[str, float]: ...

    def record(self, durations: Mapping[str, float]) -> None: ...


class InMemoryDurationStore:
    """Test double and null-object: keeps durations for this process only."""

    def __init__(self, initial: Mapping[str, float] | None = None) -> None:
        self._durations: dict[str, float] = dict(initial or {})

    def recorded_durations(self) -> dict[str, float]:
        return dict(self._durations)

    def record(self, durations: Mapping[str, float]) -> None:
        self._durations.update(durations)


class JsonFileDurationStore:
    def __init__(self, path: Path) -> None:
        self._path = path

    def recorded_durations(self) -> dict[str, float]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        if not isinstance(raw, dict):
            return {}
        return {
            str(name): float(seconds)
            for name, seconds in raw.items()
            if isinstance(seconds, (int, float))
        }

    def record(self, durations: Mapping[str, float]) -> None:
        merged = self.recorded_durations()
        merged.update(durations)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(merged, indent=2), encoding="utf-8")


def duration_store_for_rootdir(rootpath: Path) -> JsonFileDurationStore:
    return JsonFileDurationStore(rootpath / _CACHE_RELATIVE_PATH / _DURATIONS_FILENAME)
