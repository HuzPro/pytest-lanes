"""Child-side run measurement for lane subprocesses.

A lane child (detected via ``PYTEST_LANES_CHILD``) measures its own run
when the executor points it at an output path via
``PYTEST_LANES_DURATIONS_OUT``:

* ``collect`` — session start to end of collection;
* ``startup`` — end of collection to the first test's setup, which is the
  fixture/environment spin-up (a container boot lands here);
* ``files`` — test-report durations summed per file;
* ``total`` — session wall time.

The parent reads the JSON after the child exits and merges it into the
duration store. Timing marks are tolerant of missing phases (a child that
collects nothing writes zero startup and no files).
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from pathlib import Path


class ChildRunRecorder:
    def __init__(
        self,
        output_path: Path,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._output_path = output_path
        self._clock = clock or time.perf_counter
        self._session_started_at: float | None = None
        self._collection_finished_at: float | None = None
        self._first_test_started_at: float | None = None
        self._file_seconds: dict[str, float] = {}

    def mark_session_start(self) -> None:
        self._session_started_at = self._clock()

    def mark_collection_finished(self) -> None:
        self._collection_finished_at = self._clock()

    def mark_test_started(self) -> None:
        if self._first_test_started_at is None:
            self._first_test_started_at = self._clock()

    def add_report_duration(self, nodeid: str, seconds: float) -> None:
        file_path = nodeid.split("::")[0]
        self._file_seconds[file_path] = self._file_seconds.get(file_path, 0.0) + seconds

    def write(self) -> None:
        now = self._clock()
        session_start = (
            self._session_started_at if self._session_started_at is not None else now
        )
        payload = {
            "total": now - session_start,
            "collect": self._elapsed_between(
                session_start, self._collection_finished_at
            ),
            "startup": self._elapsed_between(
                self._collection_finished_at, self._first_test_started_at
            ),
            "files": self._file_seconds,
        }
        self._output_path.parent.mkdir(parents=True, exist_ok=True)
        self._output_path.write_text(json.dumps(payload), encoding="utf-8")

    def _elapsed_between(self, start: float | None, end: float | None) -> float:
        if start is None or end is None:
            return 0.0
        return max(end - start, 0.0)
