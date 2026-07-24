"""Lane orchestration reporting for orchestrated pytest runs.

This module centralizes output parsing, live lane state tracking, and
terminal presentation for orchestrated multi-lane pytest execution.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Any, Protocol, TypedDict
from collections.abc import Callable

try:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table
    from rich import box

    HAS_RICH = True
except ModuleNotFoundError:  # pragma: no cover - covered when rich is installed
    HAS_RICH = False


_ANSI_ESCAPE_PATTERN = re.compile(r"\x1b\[[0-9;]*m")
_PROGRESS_PERCENT_PATTERN = re.compile(r"\[(\s*\d{1,3})%\]")
# The per-test result glyphs pytest prints before a [ NN%] progress marker.
_PROGRESS_LINE_GLYPHS = ".sFEXx"
_COLLECTED_PATTERN = re.compile(r"collected (\d+) items?")
_SUMMARY_COUNTS_PATTERN = re.compile(r"(\d+) (passed|failed|skipped|error|deselected)")

LANE_STATUS_PENDING = "pending"
LANE_STATUS_RUNNING = "running"
LANE_STATUS_PASS = "pass"
LANE_STATUS_FAIL = "fail"

PROGRESS_MIN = 0
PROGRESS_MAX = 100
PROGRESS_COMPLETE = 100

_FALLBACK_REFRESH_THROTTLE_SECONDS = 1.0
_LIVE_TABLE_REFRESH_RATE = 6

SUMMARY_TITLE = "Lane Test Summary"


class LaneResult(TypedDict):
    name: str
    exit_code: int
    duration: float
    failed_tests: list[str]
    collected_count: int
    passed_count: int
    skipped_count: int


class SummaryMetrics(TypedDict):
    sum_lane_seconds: float
    parallelism_ratio: float
    max_lane_name_width: int


def _strip_ansi(text: str) -> str:
    return _ANSI_ESCAPE_PATTERN.sub("", text)


def _compute_summary_metrics(
    lane_results: list[LaneResult],
    wall_seconds: float,
) -> SummaryMetrics:
    sum_lane_seconds = sum(result["duration"] for result in lane_results)
    parallelism_ratio = sum_lane_seconds / wall_seconds if wall_seconds > 0 else 0.0
    max_lane_name_width = max(
        (len(result["name"]) for result in lane_results), default=0
    )
    return {
        "sum_lane_seconds": sum_lane_seconds,
        "parallelism_ratio": parallelism_ratio,
        "max_lane_name_width": max_lane_name_width,
    }


def _collect_failed_test_lines(lane_results: list[LaneResult]) -> list[str]:
    failed_lines: list[str] = []
    for result in lane_results:
        for test_name in result["failed_tests"]:
            failed_lines.append(f"> [{result['name']}] {test_name}")
    return failed_lines


def _compute_aggregate_counts(
    lane_results: list[LaneResult],
) -> tuple[int, int, int, int]:
    total_collected = sum(r["collected_count"] for r in lane_results)
    total_passed = sum(r["passed_count"] for r in lane_results)
    total_failed = sum(len(r["failed_tests"]) for r in lane_results)
    total_skipped = sum(r["skipped_count"] for r in lane_results)
    return total_collected, total_passed, total_failed, total_skipped


def extract_failed_test_lines(lane_output: str) -> list[str]:
    failed: list[str] = []
    for line in lane_output.splitlines():
        stripped = _strip_ansi(line).strip()
        if not stripped.startswith("FAILED "):
            continue

        payload = stripped[len("FAILED ") :]
        test_name, _, _ = payload.partition(" - ")
        test_name = test_name.strip()
        if test_name:
            failed.append(test_name)

    return failed


def format_orchestration_summary(
    lane_results: list[LaneResult],
    wall_seconds: float,
) -> str:
    metrics = _compute_summary_metrics(lane_results, wall_seconds)
    sum_lane_seconds = metrics["sum_lane_seconds"]
    parallelism_ratio = metrics["parallelism_ratio"]
    max_lane_name_width = metrics["max_lane_name_width"]

    lines = [SUMMARY_TITLE]
    for result in lane_results:
        lane_name = result["name"].ljust(max_lane_name_width)
        status = "PASS" if result["exit_code"] == 0 else "FAIL"
        lines.append(f"> {lane_name} : {status} ({result['duration']:.2f}s)")

    lines.append(f"Parallelism ratio: {parallelism_ratio:.2f}x")

    failed_test_lines = _collect_failed_test_lines(lane_results)
    if failed_test_lines:
        lines.append("Failed tests")
        lines.extend(failed_test_lines)

    lines.append(f"Sum time without parallelization: {sum_lane_seconds:.2f}s")
    lines.append(f"Total time taken: {wall_seconds:.2f}s")

    total_collected, total_passed, total_failed, total_skipped = (
        _compute_aggregate_counts(lane_results)
    )
    lines.append(
        f"Total: {total_collected} collected | {total_passed} passed"
        f" | {total_failed} failed | {total_skipped} skipped"
    )

    return "\n".join(lines)


def _format_seconds(seconds: float | None) -> str:
    if seconds is None:
        return "--"
    if seconds < 0:
        return "0.00s"
    return f"{seconds:.2f}s"


@dataclass
class LaneState:
    name: str
    status: str = LANE_STATUS_PENDING
    started_at: float | None = None
    duration: float = 0.0
    exit_code: int | None = None
    progress_percent: int = 0
    failed_tests: list[str] = field(default_factory=list)
    collected_count: int = 0
    passed_count: int = 0
    skipped_count: int = 0
    output_lines: list[str] = field(default_factory=list)


class LaneProgressReporter:
    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.perf_counter
        self._ordered_names: list[str] = []
        self._lanes: dict[str, LaneState] = {}

    def register_lanes(self, lane_names: list[str]) -> None:
        self._ordered_names = list(lane_names)
        self._lanes = {name: LaneState(name=name) for name in lane_names}

    def mark_started(self, lane_name: str) -> None:
        lane = self._lanes[lane_name]
        lane.status = LANE_STATUS_RUNNING
        lane.started_at = self._clock()

    def _update_progress_and_counts(self, lane: LaneState, plain: str) -> None:
        progress_match = _PROGRESS_PERCENT_PATTERN.search(plain)
        if progress_match is not None:
            lane.progress_percent = max(
                PROGRESS_MIN, min(PROGRESS_MAX, int(progress_match.group(1)))
            )
            pre = plain[: progress_match.start()].rstrip()
            space_idx = pre.rfind(" ")
            last_token = pre[space_idx + 1 :] if space_idx >= 0 else pre
            if last_token and all(c in _PROGRESS_LINE_GLYPHS for c in last_token):
                lane.passed_count += last_token.count(".") + last_token.count("X")
                lane.skipped_count += last_token.count("s")

    def _update_collected_count(self, lane: LaneState, plain: str) -> None:
        collected_match = _COLLECTED_PATTERN.search(plain)
        if collected_match is not None:
            lane.collected_count = int(collected_match.group(1))

    def _update_summary_counts(self, lane: LaneState, plain: str) -> None:
        if " passed" not in plain and " skipped" not in plain:
            return
        for count_match in _SUMMARY_COUNTS_PATTERN.finditer(plain):
            count = int(count_match.group(1))
            label = count_match.group(2)
            if label == "passed":
                lane.passed_count = count
            elif label == "skipped":
                lane.skipped_count = count
            elif label == "deselected" and " passed" in plain:
                lane.collected_count -= count

    def capture_output_line(self, lane_name: str, line: str) -> None:
        lane = self._lanes[lane_name]
        cleaned = line.rstrip("\n")
        lane.output_lines.append(cleaned)
        plain = _strip_ansi(cleaned)

        self._update_progress_and_counts(lane, plain)

        extracted = extract_failed_test_lines(plain)
        if extracted:
            lane.failed_tests.extend(extracted)

        self._update_collected_count(lane, plain)
        self._update_summary_counts(lane, plain)

    def mark_finished(self, lane_name: str, exit_code: int) -> None:
        lane = self._lanes[lane_name]
        lane.exit_code = exit_code
        lane.status = LANE_STATUS_PASS if exit_code == 0 else LANE_STATUS_FAIL
        lane.progress_percent = PROGRESS_COMPLETE
        if lane.started_at is None:
            lane.duration = 0.0
            return
        lane.duration = self._clock() - lane.started_at

    def _estimate_from_progress(
        self, running_lanes: list[LaneState], now: float
    ) -> tuple[float, int]:
        progress_based_remaining = 0.0
        progress_based_count = 0
        for lane in running_lanes:
            if lane.started_at is None:
                continue
            if lane.progress_percent <= PROGRESS_MIN:
                continue

            elapsed = max(now - lane.started_at, 0.0)
            estimated_total = elapsed * (
                float(PROGRESS_MAX) / float(lane.progress_percent)
            )
            progress_based_remaining += max(estimated_total - elapsed, 0.0)
            progress_based_count += 1
        return progress_based_remaining, progress_based_count

    def _estimate_from_average(
        self, running_lanes: list[LaneState], now: float, average_duration: float
    ) -> float:
        remaining = 0.0
        for lane in running_lanes:
            if lane.progress_percent > PROGRESS_MIN and lane.started_at is not None:
                continue
            if lane.started_at is None:
                remaining += average_duration
                continue
            elapsed = now - lane.started_at
            remaining += max(average_duration - elapsed, 0.0)
        return remaining

    def estimated_remaining_seconds(self) -> float | None:
        running_lanes = [
            lane for lane in self._lanes.values() if lane.status == LANE_STATUS_RUNNING
        ]
        if not running_lanes:
            return 0.0

        now = self._clock()
        progress_based_remaining, progress_based_count = self._estimate_from_progress(
            running_lanes, now
        )

        if progress_based_count == len(running_lanes):
            return progress_based_remaining

        completed_durations = [
            lane.duration
            for lane in self._lanes.values()
            if lane.status in {LANE_STATUS_PASS, LANE_STATUS_FAIL}
        ]
        if not completed_durations:
            return progress_based_remaining if progress_based_count > 0 else None

        average_duration = sum(completed_durations) / len(completed_durations)
        remaining = progress_based_remaining + self._estimate_from_average(
            running_lanes, now, average_duration
        )
        return remaining

    def failed_tests_for(self, lane_name: str) -> list[str]:
        return list(self._lanes[lane_name].failed_tests)

    def lane_output_for(self, lane_name: str) -> str:
        return "\n".join(self._lanes[lane_name].output_lines)

    def lane_results(self) -> list[LaneResult]:
        results: list[LaneResult] = []
        for lane_name in self._ordered_names:
            lane = self._lanes[lane_name]
            results.append(
                {
                    "name": lane.name,
                    "exit_code": 0 if lane.exit_code is None else lane.exit_code,
                    "duration": lane.duration,
                    "failed_tests": list(lane.failed_tests),
                    "collected_count": lane.collected_count,
                    "passed_count": lane.passed_count,
                    "skipped_count": lane.skipped_count,
                }
            )
        return results

    def build_summary(self, wall_seconds: float) -> str:
        return format_orchestration_summary(self.lane_results(), wall_seconds)

    def live_rows(self) -> list[dict[str, str]]:
        now = self._clock()
        rows: list[dict[str, str]] = []
        for lane_name in self._ordered_names:
            lane = self._lanes[lane_name]
            if lane.status in {LANE_STATUS_PASS, LANE_STATUS_FAIL}:
                elapsed = lane.duration
            elif lane.started_at is not None:
                elapsed = now - lane.started_at
            else:
                elapsed = 0.0

            if lane.status == LANE_STATUS_PASS:
                status = "PASS"
            elif lane.status == LANE_STATUS_FAIL:
                status = "FAIL"
            else:
                status = lane.status.upper()
            rows.append(
                {
                    "name": lane_name,
                    "status": status,
                    "progress": f"{float(lane.progress_percent):.2f}%",
                    "elapsed": _format_seconds(elapsed),
                    "collected": str(lane.collected_count),
                    "passed": str(lane.passed_count),
                    "failed": str(len(lane.failed_tests)),
                    "skipped": str(lane.skipped_count),
                }
            )

        return rows


class LanePresenterDisplay(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def print_summary(
        self, reporter: LaneProgressReporter, wall_seconds: float
    ) -> None: ...

    def emit_lane_line(self, lane_name: str, line: str) -> None: ...

    def refresh(self) -> None: ...


class PlainLaneDisplay:
    def __init__(
        self,
        reporter: LaneProgressReporter,
        show_lane_stream: bool = False,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._reporter = reporter
        self._show_lane_stream = show_lane_stream
        self._clock = clock or reporter._clock
        self._last_plain_print_at = 0.0

    def start(self) -> None:
        return

    def stop(self) -> None:
        return

    def print_summary(
        self, reporter: LaneProgressReporter, wall_seconds: float
    ) -> None:
        lane_results = reporter.lane_results()
        summary_text = format_orchestration_summary(
            lane_results=lane_results,
            wall_seconds=wall_seconds,
        )
        print(summary_text)

    def emit_lane_line(self, lane_name: str, line: str) -> None:
        if not self._show_lane_stream:
            return

        stripped = line.rstrip("\n")
        if not stripped:
            return

        print(f"[{lane_name}] {stripped}")

    def refresh(self) -> None:
        now = self._clock()
        if now - self._last_plain_print_at < _FALLBACK_REFRESH_THROTTLE_SECONDS:
            return

        self._last_plain_print_at = now
        rows = self._reporter.live_rows()
        print("Lane status snapshot")
        for row in rows:
            print(
                "- "
                f"{row['name']}: {row['status']} | "
                f"progress={row['progress']} | elapsed={row['elapsed']} | "
                f"collected={row['collected']} | passed={row['passed']} | "
                f"failed={row['failed']} | skipped={row['skipped']}"
            )


class RichLaneDisplay:
    def __init__(
        self, reporter: LaneProgressReporter, show_lane_stream: bool = False
    ) -> None:
        self._reporter = reporter
        self._show_lane_stream = show_lane_stream
        self._live: Any | None = None
        self._console = Console()

    def start(self) -> None:
        self._live = Live(
            self._build_table(),
            console=self._console,
            refresh_per_second=_LIVE_TABLE_REFRESH_RATE,
        )
        self._live.start()

    def stop(self) -> None:
        if self._live is not None:
            self._live.stop()

    def _print_lane_rows(
        self, lane_results: list[LaneResult], max_lane_name_width: int
    ) -> None:
        for result in lane_results:
            lane_name = result["name"].ljust(max_lane_name_width)
            status_is_pass = result["exit_code"] == 0
            status_text = "PASS" if status_is_pass else "FAIL"
            status_style = "bold green" if status_is_pass else "bold red"
            lane_line = (
                f"> [bold]{lane_name}[/] [white]:[/] "
                f"[{status_style}]{status_text}[/] [white]({result['duration']:.2f}s)[/]"
            )
            self._console.print(lane_line)

    def _print_failed_tests_section(self, failed_lines: list[str]) -> None:
        if not failed_lines:
            return
        self._console.print("[bold red]Failed tests[/]")
        for line in failed_lines:
            self._console.print(f"[red]{line}[/]")

    def _print_totals_section(
        self,
        lane_results: list[LaneResult],
        sum_lane_seconds: float,
        wall_seconds: float,
    ) -> None:
        self._console.print(
            "[yellow]Sum time without parallelization:[/] "
            f"[bold white]{sum_lane_seconds:.2f}s[/]"
        )
        self._console.print(
            f"[bold green]Total time taken:[/] [bold white]{wall_seconds:.2f}s[/]"
        )

        total_collected, total_passed, total_failed, total_skipped = (
            _compute_aggregate_counts(lane_results)
        )
        failed_style = "bold red" if total_failed > 0 else "green"
        skipped_style = "yellow" if total_skipped > 0 else "white"
        self._console.print(
            f"[bold]Total:[/] [white]{total_collected}[/] collected"
            f" [dim]|[/] [green]{total_passed}[/] passed"
            f" [dim]|[/] [{failed_style}]{total_failed}[/] failed"
            f" [dim]|[/] [{skipped_style}]{total_skipped}[/] skipped"
        )

    def print_summary(
        self, reporter: LaneProgressReporter, wall_seconds: float
    ) -> None:
        lane_results = reporter.lane_results()
        metrics = _compute_summary_metrics(lane_results, wall_seconds)
        sum_lane_seconds = metrics["sum_lane_seconds"]
        parallelism_ratio = metrics["parallelism_ratio"]
        max_lane_name_width = metrics["max_lane_name_width"]

        self._console.print("")
        self._console.print(f"[bold cyan]{SUMMARY_TITLE}[/]")
        self._print_lane_rows(lane_results, max_lane_name_width)
        self._console.print(
            f"[blue]Parallelism ratio:[/] [bold white]{parallelism_ratio:.2f}x[/]"
        )

        failed_lines = _collect_failed_test_lines(lane_results)
        self._print_failed_tests_section(failed_lines)
        self._print_totals_section(lane_results, sum_lane_seconds, wall_seconds)

    def emit_lane_line(self, lane_name: str, line: str) -> None:
        if not self._show_lane_stream:
            return

        stripped = line.rstrip("\n")
        if not stripped:
            return

        if self._live is not None:
            self._live.console.print(f"[{lane_name}] {stripped}")
            return

        print(f"[{lane_name}] {stripped}")

    def refresh(self) -> None:
        if self._live is None:
            return

        self._live.update(self._build_table())

    def _create_table_schema(self) -> Table:
        table = Table(title="[bold cyan]Lanes[/]", show_edge=True, box=box.HEAVY)
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Progress")
        table.add_column("Elapsed")
        table.add_column("Collected")
        table.add_column("Passed")
        table.add_column("Failed")
        table.add_column("Skipped")
        return table

    def _format_row_cells(self, row: dict[str, str]) -> dict[str, str]:
        status = row["status"]
        if status == "RUNNING":
            status = "[bold yellow]RUNNING[/]"
        elif status == "PASS":
            status = "[bold green]PASS[/]"
        elif status == "FAIL":
            status = "[bold red]FAIL[/]"

        progress = row["progress"]
        if progress == "100.00%":
            progress = "[bold green]100.00%[/]"

        collected_count = int(row["collected"])
        collected = str(collected_count) if collected_count > 0 else "[dim]0[/]"

        passed_count = int(row["passed"])
        passed = f"[green]{passed_count}[/]" if passed_count > 0 else "[dim]0[/]"

        failed_count = int(row["failed"])
        failed = "[green]0[/]" if failed_count == 0 else f"[bold red]{failed_count}[/]"

        skipped_count = int(row["skipped"])
        skipped = f"[yellow]{skipped_count}[/]" if skipped_count > 0 else "[dim]0[/]"

        return {
            "name": row["name"],
            "status": status,
            "progress": progress,
            "elapsed": row["elapsed"],
            "collected": collected,
            "passed": passed,
            "failed": failed,
            "skipped": skipped,
        }

    def _build_table(self) -> object:
        table = self._create_table_schema()
        for row in self._reporter.live_rows():
            cells = self._format_row_cells(row)
            table.add_row(
                cells["name"],
                cells["status"],
                cells["progress"],
                cells["elapsed"],
                cells["collected"],
                cells["passed"],
                cells["failed"],
                cells["skipped"],
            )
        return table


def _build_default_display(
    reporter: LaneProgressReporter,
    show_lane_stream: bool,
) -> LanePresenterDisplay:
    if HAS_RICH:
        return RichLaneDisplay(reporter, show_lane_stream=show_lane_stream)
    return PlainLaneDisplay(reporter, show_lane_stream=show_lane_stream)


class LaneConsolePresenter:
    def __init__(
        self,
        reporter: LaneProgressReporter,
        show_lane_stream: bool = False,
        display_factory: Callable[[LaneProgressReporter, bool], LanePresenterDisplay]
        | None = None,
    ) -> None:
        factory = _build_default_display if display_factory is None else display_factory
        self._display = factory(reporter, show_lane_stream)

    def start(self) -> None:
        self._display.start()

    def stop(self) -> None:
        self._display.stop()

    def print_summary(
        self, reporter: LaneProgressReporter, wall_seconds: float
    ) -> None:
        self._display.print_summary(reporter, wall_seconds)

    def emit_lane_line(self, lane_name: str, line: str) -> None:
        self._display.emit_lane_line(lane_name, line)

    def refresh(self) -> None:
        self._display.refresh()
