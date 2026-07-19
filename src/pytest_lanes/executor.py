"""Parallel lane subprocess executor for orchestrated pytest runs.

Each lane runs as its own ``python -m pytest`` subprocess. Output is streamed
line-by-line from each child process into a shared queue, drained by the main
loop into the lane reporter and console presenter. Children detect the parent
via :data:`TEST_ORCHESTRATION_CHILD_ENV` so they skip re-orchestration.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

from pytest_lanes.constants import (
    LANE_POLL_INTERVAL_SECONDS,
    SHOW_LANE_OUTPUT_ENV,
    TEST_ORCHESTRATION_CHILD_ENV,
)
from pytest_lanes.lanes import LaneCommand
from pytest_lanes.reporter import LaneConsolePresenter, LaneProgressReporter


@dataclass
class _LaneRun:
    name: str
    process: subprocess.Popen[str]
    exit_code: int | None = None


def run_lane_commands(commands: list[LaneCommand]) -> int:
    start_wall = time.perf_counter()
    lane_output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
    show_lane_output = os.environ.get(SHOW_LANE_OUTPUT_ENV) == "1"
    reporter = LaneProgressReporter()
    reporter.register_lanes([command.name for command in commands])
    presenter = LaneConsolePresenter(reporter, show_lane_stream=show_lane_output)

    runs, readers = _launch_lanes(commands, reporter, lane_output_queue)
    presenter.start()
    try:
        _poll_until_finished(runs, lane_output_queue, reporter, presenter)
    finally:
        for reader in readers:
            reader.join(timeout=0.2)
        presenter.stop()

    _print_lane_outputs(reporter, show_lane_output)

    wall_seconds = time.perf_counter() - start_wall
    presenter.print_summary(reporter, wall_seconds=wall_seconds)

    exit_codes = [result["exit_code"] for result in reporter.lane_results()]
    return max(exit_codes) if exit_codes else 0


def _launch_lanes(
    commands: list[LaneCommand],
    reporter: LaneProgressReporter,
    lane_output_queue: queue.Queue[tuple[str, str]],
) -> tuple[list[_LaneRun], list[threading.Thread]]:
    runs: list[_LaneRun] = []
    readers: list[threading.Thread] = []
    for command in commands:
        process = _spawn_lane_subprocess(command)
        reporter.mark_started(command.name)
        reader = threading.Thread(
            target=stream_lane_output,
            args=(command.name, process, lane_output_queue),
            daemon=True,
        )
        reader.start()
        readers.append(reader)
        runs.append(_LaneRun(name=command.name, process=process))
    return runs, readers


def _spawn_lane_subprocess(command: LaneCommand) -> subprocess.Popen[str]:
    env = os.environ.copy()
    env[TEST_ORCHESTRATION_CHILD_ENV] = "1"
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


def _poll_until_finished(
    runs: list[_LaneRun],
    lane_output_queue: queue.Queue[tuple[str, str]],
    reporter: LaneProgressReporter,
    presenter: LaneConsolePresenter,
) -> None:
    unfinished_count = len(runs)
    while unfinished_count > 0:
        drain_lane_output_queue(lane_output_queue, reporter, presenter)

        for run in runs:
            if run.exit_code is not None:
                continue
            return_code = run.process.poll()
            if return_code is None:
                continue
            run.exit_code = return_code
            reporter.mark_finished(run.name, return_code)
            unfinished_count -= 1

        presenter.refresh()
        if unfinished_count > 0:
            time.sleep(LANE_POLL_INTERVAL_SECONDS)

    drain_lane_output_queue(lane_output_queue, reporter, presenter)


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
