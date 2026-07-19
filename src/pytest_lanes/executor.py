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

from pytest_lanes.constants import (
    LANE_POLL_INTERVAL_SECONDS,
    SHOW_LANE_OUTPUT_ENV,
    TEST_ORCHESTRATION_CHILD_ENV,
)
from pytest_lanes.reporter import LaneConsolePresenter, LaneProgressReporter


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


def run_lane_commands(commands: list[dict[str, list[str]]]) -> int:
    start_wall = time.perf_counter()
    lane_records: list[dict[str, str | int | subprocess.Popen[str] | None]] = []
    lane_reader_threads: list[threading.Thread] = []
    lane_output_queue: queue.Queue[tuple[str, str]] = queue.Queue()
    show_lane_output = os.environ.get(SHOW_LANE_OUTPUT_ENV) == "1"
    reporter = LaneProgressReporter()
    reporter.register_lanes([command["name"] for command in commands])
    presenter = LaneConsolePresenter(reporter, show_lane_stream=show_lane_output)

    for command in commands:
        lane_name = command["name"]
        env = os.environ.copy()
        env[TEST_ORCHESTRATION_CHILD_ENV] = "1"
        for key, value in command.get("env_set", ()):
            env[key] = value
        process: subprocess.Popen[str] = subprocess.Popen(
            [sys.executable, "-m", "pytest", *command["args"]],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
        reporter.mark_started(lane_name)
        lane_reader = threading.Thread(
            target=stream_lane_output,
            args=(lane_name, process, lane_output_queue),
            daemon=True,
        )
        lane_reader.start()
        lane_reader_threads.append(lane_reader)
        lane_records.append(
            {
                "name": lane_name,
                "process": process,
                "exit_code": None,
            }
        )

    presenter.start()
    unfinished_count = len(lane_records)
    try:
        while unfinished_count > 0:
            drain_lane_output_queue(lane_output_queue, reporter, presenter)

            for lane in lane_records:
                if lane["exit_code"] is not None:
                    continue

                process = lane["process"]
                if not isinstance(process, subprocess.Popen):
                    continue

                return_code = process.poll()
                if return_code is None:
                    continue

                lane_name = str(lane["name"])
                lane["exit_code"] = return_code
                reporter.mark_finished(lane_name, return_code)
                unfinished_count -= 1

            presenter.refresh()
            if unfinished_count > 0:
                time.sleep(LANE_POLL_INTERVAL_SECONDS)

        drain_lane_output_queue(lane_output_queue, reporter, presenter)
    finally:
        for lane_reader in lane_reader_threads:
            lane_reader.join(timeout=0.2)
        presenter.stop()

    lane_results = reporter.lane_results()
    for lane_result in lane_results:
        lane_name = str(lane_result["name"])
        exit_code = int(lane_result["exit_code"])
        if show_lane_output or exit_code != 0:
            print(f"\n----- {lane_name} lane output -----")
            print(reporter.lane_output_for(lane_name).rstrip())
            print(f"----- end {lane_name} lane output -----")

    wall_seconds = time.perf_counter() - start_wall
    presenter.print_summary(reporter, wall_seconds=wall_seconds)

    exit_codes = [int(result["exit_code"]) for result in lane_results]
    return max(exit_codes) if exit_codes else 0
