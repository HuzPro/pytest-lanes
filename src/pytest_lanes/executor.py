"""Parallel lane subprocess executor for orchestrated pytest runs.

Each lane runs as its own ``python -m pytest`` subprocess. At most
``max_workers`` lanes run concurrently; the rest wait in a
:class:`~pytest_lanes.scheduler.LaneWorkQueue` and launch as slots free up.
Output is streamed line-by-line from each child process into a shared queue,
drained by the main loop into the lane reporter and console presenter.
Children detect the parent via :data:`TEST_ORCHESTRATION_CHILD_ENV` so they
skip re-orchestration.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from pytest import ExitCode

from pytest_lanes.constants import (
    CHILD_DURATIONS_OUT_ENV,
    LANE_POLL_INTERVAL_SECONDS,
    SHOW_LANE_OUTPUT_ENV,
    TEST_ORCHESTRATION_CHILD_ENV,
)
from pytest_lanes.durations import DurationStore, InMemoryDurationStore, LaneRecord
from pytest_lanes.lanes import LaneCommand
from pytest_lanes.reporter import LaneConsolePresenter, LaneProgressReporter
from pytest_lanes.scheduler import LaneWorkQueue, ordering_policy_for


@dataclass
class _LaneRun:
    name: str
    process: subprocess.Popen[str]
    exit_code: int | None = None
    tolerate_no_tests: bool = False


@dataclass
class _RunContext:
    lane_output_queue: queue.Queue[tuple[str, str]]
    reporter: LaneProgressReporter
    presenter: LaneConsolePresenter
    durations_dir: Path


def run_lane_commands(
    commands: list[LaneCommand],
    max_workers: int,
    duration_store: DurationStore | None = None,
) -> int:
    start_wall = time.perf_counter()
    show_lane_output = os.environ.get(SHOW_LANE_OUTPUT_ENV) == "1"
    store = duration_store if duration_store is not None else InMemoryDurationStore()
    recorded_durations = store.recorded_durations()
    reporter = LaneProgressReporter(expected_durations=recorded_durations)
    reporter.register_lanes([command.name for command in commands])
    context = _RunContext(
        lane_output_queue=queue.Queue(),
        reporter=reporter,
        presenter=LaneConsolePresenter(reporter, show_lane_stream=show_lane_output),
        durations_dir=Path(tempfile.mkdtemp(prefix="pytest-lanes-durations-")),
    )
    work_queue = LaneWorkQueue(
        commands,
        max_workers=max_workers,
        policy=ordering_policy_for(recorded_durations),
    )

    runs: list[_LaneRun] = []
    readers: list[threading.Thread] = []
    context.presenter.start()
    try:
        _run_scheduling_loop(work_queue, context, runs, readers)
    finally:
        for reader in readers:
            reader.join(timeout=0.2)
        context.presenter.stop()

    _print_lane_outputs(reporter, show_lane_output)

    wall_seconds = time.perf_counter() - start_wall
    context.presenter.print_summary(reporter, wall_seconds=wall_seconds)

    _record_run_durations(reporter, store, context.durations_dir)
    shutil.rmtree(context.durations_dir, ignore_errors=True)

    exit_codes = [result["exit_code"] for result in reporter.lane_results()]
    return max(exit_codes) if exit_codes else 0


def _record_run_durations(
    reporter: LaneProgressReporter,
    store: DurationStore,
    durations_dir: Path,
) -> None:
    finished: dict[str, LaneRecord] = {}
    for result in reporter.lane_results():
        if result["duration"] <= 0:
            continue
        measured = _read_child_measurements(durations_dir / f"{result['name']}.json")
        finished[result["name"]] = LaneRecord(
            total=result["duration"],
            startup=float(measured.get("startup", 0.0)),
            collect=float(measured.get("collect", 0.0)),
            files=tuple(sorted(dict(measured.get("files", {})).items())),
        )
    if finished:
        store.record(finished)


def _read_child_measurements(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _run_scheduling_loop(
    work_queue: LaneWorkQueue,
    context: _RunContext,
    runs: list[_LaneRun],
    readers: list[threading.Thread],
) -> None:
    """Launch lanes as worker slots allow and poll until every lane finishes.

    ``runs`` and ``readers`` are appended in place so the caller can join
    reader threads even when the loop exits via an exception (Ctrl+C); no
    new lane launches after that point.
    """
    while not work_queue.is_done():
        for command in work_queue.ready_to_launch():
            run, reader = _launch_single_lane(command, context)
            work_queue.mark_launched(command.name)
            runs.append(run)
            readers.append(reader)

        drain_lane_output_queue(
            context.lane_output_queue, context.reporter, context.presenter
        )
        _record_finished_lanes(runs, context.reporter, work_queue)
        context.presenter.refresh()
        if not work_queue.is_done():
            time.sleep(LANE_POLL_INTERVAL_SECONDS)

    drain_lane_output_queue(
        context.lane_output_queue, context.reporter, context.presenter
    )


def _launch_single_lane(
    command: LaneCommand, context: _RunContext
) -> tuple[_LaneRun, threading.Thread]:
    process = _spawn_lane_subprocess(command, context.durations_dir)
    context.reporter.mark_started(command.name)
    reader = threading.Thread(
        target=stream_lane_output,
        args=(command.name, process, context.lane_output_queue),
        daemon=True,
    )
    reader.start()
    run = _LaneRun(
        name=command.name,
        process=process,
        tolerate_no_tests=command.tolerate_no_tests,
    )
    return run, reader


def _record_finished_lanes(
    runs: list[_LaneRun],
    reporter: LaneProgressReporter,
    work_queue: LaneWorkQueue,
) -> None:
    for run in runs:
        if run.exit_code is not None:
            continue
        return_code = run.process.poll()
        if return_code is None:
            continue
        if run.tolerate_no_tests and return_code == int(ExitCode.NO_TESTS_COLLECTED):
            return_code = 0
        run.exit_code = return_code
        reporter.mark_finished(run.name, return_code)
        work_queue.mark_finished(run.name)


def _spawn_lane_subprocess(
    command: LaneCommand, durations_dir: Path
) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env[TEST_ORCHESTRATION_CHILD_ENV] = "1"
    env[CHILD_DURATIONS_OUT_ENV] = str(durations_dir / f"{command.name}.json")
    for key, value in command.env_set:
        env[key] = value
    return subprocess.Popen(
        [sys.executable, "-m", "pytest", *command.args],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def _print_lane_outputs(reporter: LaneProgressReporter, show_lane_output: bool) -> None:
    for result in reporter.lane_results():
        if not show_lane_output and result["exit_code"] == 0:
            continue
        lane_name = result["name"]
        print(f"\n----- {lane_name} lane output -----")
        print(reporter.lane_output_for(lane_name).rstrip())
        print(f"----- end {lane_name} lane output -----")


def stream_lane_output(
    lane_name: str,
    process: subprocess.Popen[str],
    lane_output_queue: queue.Queue[tuple[str, str]],
) -> None:
    if process.stdout is None:
        return

    for line in process.stdout:
        lane_output_queue.put((lane_name, line))

    process.stdout.close()


def drain_lane_output_queue(
    lane_output_queue: queue.Queue[tuple[str, str]],
    reporter: LaneProgressReporter,
    presenter: LaneConsolePresenter,
) -> None:
    while True:
        try:
            lane_name, line = lane_output_queue.get_nowait()
        except queue.Empty:
            return

        reporter.capture_output_line(lane_name, line)
        presenter.emit_lane_line(lane_name, line)
