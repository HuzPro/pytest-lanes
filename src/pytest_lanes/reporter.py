"""Lane orchestration reporting for orchestrated pytest runs."""

from __future__ import annotations

import importlib.util
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, NamedTuple, Protocol, TypedDict

if TYPE_CHECKING:
    from rich.console import Console
    from rich.live import Live
    from rich.table import Table

# Imported lazily: rich is over half this plugin's import cost, paid by every pytest run.
HAS_RICH = importlib.util.find_spec("rich") is not None


def new_console() -> Console:
    """The rich console for the live display, imported on first use."""
    from rich.console import Console

    return Console()


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

_FALLBACK_REFRESH_THROTTLE_SECONDS = 1.0
_LIVE_TABLE_REFRESH_RATE = 6

SUMMARY_TITLE = "Lane Test Summary"


class LaneResult(TypedDict):
    name: str
    exit_code: int
    duration: float
    reproduce_lines: list[str]
    failed_tests: list[str]
    collected_count: int
    passed_count: int
    skipped_count: int


class LaneRow(NamedTuple):
    """One lane's live state, in the shape the displays render."""

    name: str
    status: str
    progress_percent: int
    elapsed_seconds: float
    collected: int
    passed: int
    failed: int
    skipped: int


@dataclass(frozen=True)
class SummaryMetrics:
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
    return SummaryMetrics(
        sum_lane_seconds=sum_lane_seconds,
        parallelism_ratio=parallelism_ratio,
        max_lane_name_width=max_lane_name_width,
    )


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

    lines = [SUMMARY_TITLE]
    for result in lane_results:
        lane_name = result["name"].ljust(metrics.max_lane_name_width)
        status = "PASS" if result["exit_code"] == 0 else "FAIL"
        lines.append(f"> {lane_name} : {status} ({result['duration']:.2f}s)")
        if result["exit_code"] != 0:
            first_line, *rest = result["reproduce_lines"]
            lines.append(f"  reproduce: {first_line}")
            lines.extend(f"  or: {line}" for line in rest)

    lines.append(f"Parallelism ratio: {metrics.parallelism_ratio:.2f}x")

    failed_test_lines = _collect_failed_test_lines(lane_results)
    if failed_test_lines:
        lines.append("Failed tests")
        lines.extend(failed_test_lines)

    lines.append(f"Sum time without parallelization: {metrics.sum_lane_seconds:.2f}s")
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


def _format_percent(percent: int) -> str:
    return f"{float(percent):.2f}%"


_STATUS_STYLES: Mapping[str, str] = {
    "RUNNING": "bold yellow",
    "PASS": "bold green",
    "FAIL": "bold red",
}


def _styled(text: str, style: str) -> str:
    return f"[{style}]{text}[/]" if style else text


def _styled_count(count: int, nonzero_style: str, zero_style: str) -> str:
    return _styled(str(count), nonzero_style if count else zero_style)


def _reports_progress(lane: LaneState) -> bool:
    """Whether this lane has told us enough to extrapolate its own finish time."""
    return lane.started_at is not None and lane.progress_percent > PROGRESS_MIN


@dataclass
class LaneState:
    name: str
    status: str = LANE_STATUS_PENDING
    reproduce_lines: tuple[str, ...] = ()
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
    def __init__(
        self,
        clock: Callable[[], float] | None = None,
        expected_durations: Mapping[str, float] | None = None,
    ) -> None:
        self._clock = clock or time.perf_counter
        self._ordered_names: list[str] = []
        self._lanes: dict[str, LaneState] = {}
        self._expected_durations = dict(expected_durations or {})

    @property
    def clock(self) -> Callable[[], float]:
        """The time source this reporter measures with, shared by its displays."""
        return self._clock

    def register_lanes(
        self,
        lane_names: list[str],
        reproduce_overrides: Mapping[str, tuple[str, ...]] | None = None,
    ) -> None:
        overrides = reproduce_overrides or {}
        self._ordered_names = list(lane_names)
        self._lanes = {
            name: LaneState(name=name, reproduce_lines=overrides.get(name, ()))
            for name in lane_names
        }

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
        lane.progress_percent = PROGRESS_MAX
        if lane.started_at is None:
            lane.duration = 0.0
            return
        lane.duration = self._clock() - lane.started_at

    def mark_unreported(self, lane_name: str, exit_code: int) -> None:
        """Record a lane that never reported an outcome, so it reads as failed."""
        lane = self._lanes[lane_name]
        lane.exit_code = exit_code
        lane.status = LANE_STATUS_FAIL
        if lane.started_at is not None:
            lane.duration = self._clock() - lane.started_at

    def estimated_remaining_seconds(self) -> float | None:
        pending_expected = self._pending_lanes_expected_seconds()
        running_lanes = [
            lane for lane in self._lanes.values() if lane.status == LANE_STATUS_RUNNING
        ]
        if not running_lanes:
            return pending_expected

        measurable = [lane for lane in running_lanes if _reports_progress(lane)]
        unmeasurable = [lane for lane in running_lanes if not _reports_progress(lane)]
        average_duration = self._completed_average_seconds() if unmeasurable else None
        if average_duration is None and not measurable:
            return pending_expected if pending_expected > 0 else None

        now = self._clock()
        unmeasured_remaining = (
            0.0
            if average_duration is None
            else self._estimate_from_average(unmeasurable, now, average_duration)
        )
        return (
            self._estimate_from_progress(measurable, now)
            + unmeasured_remaining
            + pending_expected
        )

    def _estimate_from_progress(self, lanes: list[LaneState], now: float) -> float:
        """Extrapolate each lane's own reported percentage to a total."""
        remaining = 0.0
        for lane in lanes:
            elapsed = max(now - (lane.started_at or 0.0), 0.0)
            estimated_total = elapsed * (
                float(PROGRESS_MAX) / float(lane.progress_percent)
            )
            remaining += max(estimated_total - elapsed, 0.0)
        return remaining

    def _estimate_from_average(
        self, lanes: list[LaneState], now: float, average_duration: float
    ) -> float:
        """Fall back to the average completed lane for lanes with no progress yet."""
        remaining = 0.0
        for lane in lanes:
            if lane.started_at is None:
                remaining += average_duration
                continue
            remaining += max(average_duration - (now - lane.started_at), 0.0)
        return remaining

    def _completed_average_seconds(self) -> float | None:
        durations = [
            lane.duration
            for lane in self._lanes.values()
            if lane.status in {LANE_STATUS_PASS, LANE_STATUS_FAIL}
        ]
        if not durations:
            return None
        return sum(durations) / len(durations)

    def _pending_lanes_expected_seconds(self) -> float:
        return sum(
            self._expected_durations.get(lane.name, 0.0)
            for lane in self._lanes.values()
            if lane.status == LANE_STATUS_PENDING
        )

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
                    "reproduce_lines": list(
                        lane.reproduce_lines or (f"pytest --lane={lane.name}",)
                    ),
                    "failed_tests": list(lane.failed_tests),
                    "collected_count": lane.collected_count,
                    "passed_count": lane.passed_count,
                    "skipped_count": lane.skipped_count,
                }
            )
        return results

    def build_summary(self, wall_seconds: float) -> str:
        return format_orchestration_summary(self.lane_results(), wall_seconds)

    def live_rows(self) -> list[LaneRow]:
        now = self._clock()
        return [
            self._row_for(self._lanes[lane_name], now)
            for lane_name in self._ordered_names
        ]

    def _row_for(self, lane: LaneState, now: float) -> LaneRow:
        return LaneRow(
            name=lane.name,
            status=lane.status.upper(),
            progress_percent=lane.progress_percent,
            elapsed_seconds=self._elapsed_seconds_for(lane, now),
            collected=lane.collected_count,
            passed=lane.passed_count,
            failed=len(lane.failed_tests),
            skipped=lane.skipped_count,
        )

    def _elapsed_seconds_for(self, lane: LaneState, now: float) -> float:
        if lane.status in {LANE_STATUS_PASS, LANE_STATUS_FAIL}:
            return lane.duration
        if lane.started_at is None:
            return 0.0
        return now - lane.started_at


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
    ) -> None:
        self._reporter = reporter
        self._show_lane_stream = show_lane_stream
        self._clock = reporter.clock
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
        eta = _format_seconds(self._reporter.estimated_remaining_seconds())
        print(f"Lane status snapshot (eta {eta})")
        for row in rows:
            print(
                "- "
                f"{row.name}: {row.status} | "
                f"progress={_format_percent(row.progress_percent)} | "
                f"elapsed={_format_seconds(row.elapsed_seconds)} | "
                f"collected={row.collected} | passed={row.passed} | "
                f"failed={row.failed} | skipped={row.skipped}"
            )


class RichLaneDisplay:
    def __init__(
        self, reporter: LaneProgressReporter, show_lane_stream: bool = False
    ) -> None:
        self._reporter = reporter
        self._show_lane_stream = show_lane_stream
        self._live: Live | None = None
        self._console = new_console()
        self._clock = reporter.clock
        self._last_table_built_at = 0.0

    def start(self) -> None:
        from rich.live import Live

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
            lane_line = (
                f"> [bold]{lane_name}[/] [white]:[/] "
                f"{_styled(status_text, _STATUS_STYLES[status_text])} "
                f"[white]({result['duration']:.2f}s)[/]"
            )
            self._console.print(lane_line)
            if not status_is_pass:
                first_line, *rest = result["reproduce_lines"]
                self._console.print(f"  [dim]reproduce:[/] {first_line}")
                for line in rest:
                    self._console.print(f"  [dim]or:[/] {line}")

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
        self._console.print(
            f"[bold]Total:[/] {_styled(str(total_collected), 'white')} collected"
            f" [dim]|[/] {_styled(str(total_passed), 'green')} passed"
            f" [dim]|[/] {_styled_count(total_failed, 'bold red', 'green')} failed"
            f" [dim]|[/] {_styled_count(total_skipped, 'yellow', 'white')} skipped"
        )

    def print_summary(
        self, reporter: LaneProgressReporter, wall_seconds: float
    ) -> None:
        lane_results = reporter.lane_results()
        metrics = _compute_summary_metrics(lane_results, wall_seconds)

        self._console.print("")
        self._console.print(f"[bold cyan]{SUMMARY_TITLE}[/]")
        self._print_lane_rows(lane_results, metrics.max_lane_name_width)
        self._console.print(
            f"[blue]Parallelism ratio:[/] [bold white]{metrics.parallelism_ratio:.2f}x[/]"
        )

        failed_lines = _collect_failed_test_lines(lane_results)
        self._print_failed_tests_section(failed_lines)
        self._print_totals_section(lane_results, metrics.sum_lane_seconds, wall_seconds)

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
        now = self._clock()
        if now - self._last_table_built_at < 1.0 / _LIVE_TABLE_REFRESH_RATE:
            return

        self._last_table_built_at = now
        self._live.update(self._build_table())

    def _create_table_schema(self, caption: str) -> Table:
        from rich import box
        from rich.table import Table

        table = Table(
            title="[bold cyan]Lanes[/]",
            caption=caption,
            show_edge=True,
            box=box.HEAVY,
        )
        table.add_column("Type")
        table.add_column("Status")
        table.add_column("Progress")
        table.add_column("Elapsed")
        table.add_column("Collected")
        table.add_column("Passed")
        table.add_column("Failed")
        table.add_column("Skipped")
        return table

    def _row_cells(self, row: LaneRow) -> tuple[str, ...]:
        """One cell per column, in the order ``_create_table_schema`` declares."""
        return (
            row.name,
            _styled(row.status, _STATUS_STYLES.get(row.status, "")),
            self._progress_cell(row),
            _format_seconds(row.elapsed_seconds),
            _styled_count(row.collected, "", "dim"),
            _styled_count(row.passed, "green", "dim"),
            _styled_count(row.failed, "bold red", "green"),
            _styled_count(row.skipped, "yellow", "dim"),
        )

    def _progress_cell(self, row: LaneRow) -> str:
        text = _format_percent(row.progress_percent)
        is_complete = row.progress_percent >= PROGRESS_MAX
        return _styled(text, "bold green") if is_complete else text

    def _build_table(self) -> Table:
        eta = _format_seconds(self._reporter.estimated_remaining_seconds())
        table = self._create_table_schema(caption=f"eta {eta}")
        for row in self._reporter.live_rows():
            table.add_row(*self._row_cells(row))
        return table


def build_lane_display(
    reporter: LaneProgressReporter,
    show_lane_stream: bool = False,
) -> LanePresenterDisplay:
    """The richest display this environment supports."""
    if HAS_RICH:
        try:
            return RichLaneDisplay(reporter, show_lane_stream=show_lane_stream)
        except ModuleNotFoundError:  # pragma: no cover
            pass
    return PlainLaneDisplay(reporter, show_lane_stream=show_lane_stream)
