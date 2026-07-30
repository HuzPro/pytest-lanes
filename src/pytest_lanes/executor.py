"""Parallel lane subprocess executor for orchestrated pytest runs."""

from __future__ import annotations

import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pytest import ExitCode

from pytest_lanes.constants import (
    CHILD_DURATIONS_OUT_ENV,
    ENV_ENABLED,
    LANE_POLL_INTERVAL_SECONDS,
    SHOW_LANE_OUTPUT_ENV,
    TEST_ORCHESTRATION_CHILD_ENV,
    env_flag_enabled,
)
from pytest_lanes.durations import (
    DurationStore,
    InMemoryDurationStore,
    LaneRecord,
    lane_record_from_file,
)
from pytest_lanes.lanes import LaneCommand
from pytest_lanes.report_aggregation import (
    aggregate_lane_reports,
    prepare_lane_reports,
)
from pytest_lanes.reporter import (
    LanePresenterDisplay,
    LaneProgressReporter,
    build_lane_display,
)
from pytest_lanes.scheduler import LaneWorkQueue, ordering_policy_for

UNFINISHED_LANE_EXIT_CODE = int(ExitCode.INTERNAL_ERROR)


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
    presenter: LanePresenterDisplay
    durations_dir: Path


def run_lane_commands(
    commands: list[LaneCommand],
    max_workers: int,
    duration_store: DurationStore | None = None,
    shard_parents: Mapping[str, str] | None = None,
    reproduce_overrides: Mapping[str, tuple[str, ...]] | None = None,
    show_lane_output: bool = False,
) -> int:
    start_wall = time.perf_counter()
    # The env var predates the flag; CI jobs use it without changing the command.
    show_lane_output = show_lane_output or env_flag_enabled(SHOW_LANE_OUTPUT_ENV)
    reports_dir = Path(tempfile.mkdtemp(prefix="pytest-lanes-reports-"))
    commands, report_plan = prepare_lane_reports(commands, staging_dir=reports_dir)
    store = duration_store if duration_store is not None else InMemoryDurationStore()
    recorded_durations = store.recorded_durations()
    reporter = LaneProgressReporter(expected_durations=recorded_durations)
    reporter.register_lanes(
        [command.name for command in commands],
        reproduce_overrides=reproduce_overrides,
    )
    context = _RunContext(
        lane_output_queue=queue.Queue(),
        reporter=reporter,
        presenter=build_lane_display(reporter, show_lane_stream=show_lane_output),
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

    _mark_unreported_lanes(reporter, runs, commands)
    _print_lane_outputs(reporter, show_lane_output)

    aggregate_lane_reports(report_plan, [command.name for command in commands])

    wall_seconds = time.perf_counter() - start_wall
    context.presenter.print_summary(reporter, wall_seconds=wall_seconds)

    _record_run_durations(
        reporter, store, context.durations_dir, shard_parents=shard_parents
    )
    # Deleting a large coverage/html staging tree must not delay the summary.
    shutil.rmtree(reports_dir, ignore_errors=True)
    shutil.rmtree(context.durations_dir, ignore_errors=True)

    return _run_exit_code(runs, expected_lane_count=len(commands))


def _run_exit_code(runs: Sequence[_LaneRun], expected_lane_count: int) -> int:
    """The worst lane outcome; a lane that never reported one has not passed."""
    codes = [
        UNFINISHED_LANE_EXIT_CODE if run.exit_code is None else run.exit_code
        for run in runs
    ]
    if len(codes) < expected_lane_count:
        codes.append(UNFINISHED_LANE_EXIT_CODE)
    return max(codes, default=0)


def _mark_unreported_lanes(
    reporter: LaneProgressReporter,
    runs: Sequence[_LaneRun],
    commands: Sequence[LaneCommand],
) -> None:
    """Tell the reporter about lanes that never reported, so the summary agrees."""
    reported = {run.name for run in runs if run.exit_code is not None}
    for command in commands:
        if command.name not in reported:
            reporter.mark_unreported(command.name, UNFINISHED_LANE_EXIT_CODE)


def _record_run_durations(
    reporter: LaneProgressReporter,
    store: DurationStore,
    durations_dir: Path,
    shard_parents: Mapping[str, str] | None = None,
) -> None:
    parents = dict(shard_parents or {})
    finished: dict[str, LaneRecord] = {}
    shard_measurements: dict[str, list[LaneRecord]] = {}

    for result in reporter.lane_results():
        if result["duration"] <= 0:
            continue
        measured = lane_record_from_file(durations_dir / f"{result['name']}.json")
        parent = parents.get(result["name"])
        if parent is not None:
            shard_measurements.setdefault(parent, []).append(measured)
            continue
        # The parent's wall time is authoritative over the child's self-report.
        finished[result["name"]] = replace(
            measured, total=result["duration"], files=tuple(sorted(measured.files))
        )

    for parent, measurements in shard_measurements.items():
        finished[parent] = _merged_parent_record(measurements)

    if finished:
        store.record(finished)


def _merged_parent_record(measurements: list[LaneRecord]) -> LaneRecord:
    """Fold shard measurements into one whole-lane record."""
    files: dict[str, float] = {}
    for measured in measurements:
        files.update(measured.files)
    startup = max((measured.startup for measured in measurements), default=0.0)
    collect = max((measured.collect for measured in measurements), default=0.0)
    return LaneRecord(
        total=startup + collect + sum(files.values()),
        startup=startup,
        collect=collect,
        files=tuple(sorted(files.items())),
    )


def _run_scheduling_loop(
    work_queue: LaneWorkQueue,
    context: _RunContext,
    runs: list[_LaneRun],
    readers: list[threading.Thread],
) -> None:
    """Launch lanes as worker slots allow and poll until every lane finishes."""
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
    env[TEST_ORCHESTRATION_CHILD_ENV] = ENV_ENABLED
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
    presenter: LanePresenterDisplay,
) -> None:
    while True:
        try:
            lane_name, line = lane_output_queue.get_nowait()
        except queue.Empty:
            return

        reporter.capture_output_line(lane_name, line)
        presenter.emit_lane_line(lane_name, line)
