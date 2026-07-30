import re
from typing import Any

import pytest

import pytest_lanes.reporter as lane_reporter
from pytest_lanes.reporter import (
    SUMMARY_TITLE,
    LaneConsolePresenter,
    LaneProgressReporter,
    extract_failed_test_lines,
)


def test_register_and_complete_lane_extracts_failed_tests() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["postgres"])
    reporter.mark_started("postgres")

    reporter.capture_output_line(
        "postgres",
        "FAILED tests/test_alpha.py::test_one - AssertionError: boom",
    )
    reporter.capture_output_line(
        "postgres",
        "FAILED tests/test_beta.py::TestSuite::test_two - ValueError: bad",
    )
    reporter.mark_finished("postgres", exit_code=1)

    failed_tests = reporter.failed_tests_for("postgres")
    assert failed_tests == [
        "tests/test_alpha.py::test_one",
        "tests/test_beta.py::TestSuite::test_two",
    ]


def test_estimated_remaining_seconds_uses_completed_lane_average() -> None:
    now = {"value": 10.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(clock=fake_clock)
    reporter.register_lanes(["postgres", "other"])

    reporter.mark_started("postgres")
    reporter.mark_started("other")

    now["value"] = 22.0
    reporter.mark_finished("postgres", exit_code=0)

    # postgres took 12s, other has run 12s so far, estimate should be >= 0 and deterministic.
    remaining = reporter.estimated_remaining_seconds()

    assert remaining is not None
    assert remaining == 0.0


def test_estimated_remaining_seconds_uses_progress_when_available() -> None:
    now = {"value": 10.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(clock=fake_clock)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    now["value"] = 30.0
    reporter.capture_output_line("other", "test_file.py .................... [ 50%]")

    remaining = reporter.estimated_remaining_seconds()

    # With 20s elapsed at 50%, estimated total is 40s so remaining should be 20s.
    assert remaining is not None
    assert remaining == 20.0


def test_summary_text_contains_parallelism_and_failed_rollup() -> None:
    now = {"value": 0.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(clock=fake_clock)
    reporter.register_lanes(["postgres", "other"])

    reporter.mark_started("postgres")
    reporter.mark_started("other")

    now["value"] = 15.0
    reporter.capture_output_line(
        "postgres",
        "FAILED tests/test_alpha.py::test_one - AssertionError: boom",
    )
    reporter.mark_finished("postgres", exit_code=1)

    now["value"] = 20.0
    reporter.mark_finished("other", exit_code=0)

    summary = reporter.build_summary(wall_seconds=20.0)

    assert SUMMARY_TITLE in summary
    assert "Parallelism ratio: 1.75x" in summary
    assert re.search(
        r"^>\s*postgres\s*:\s*FAIL \(15\.00s\)$", summary, flags=re.MULTILINE
    )
    assert re.search(r"^>\s*other\s*:\s*PASS \(20\.00s\)$", summary, flags=re.MULTILINE)
    assert "Sum time without parallelization: 35.00s" in summary
    assert "Total time taken: 20.00s" in summary
    assert "> [postgres] tests/test_alpha.py::test_one" in summary
    assert "Total:" in summary


def test_extract_failed_test_lines_strips_ansi_escape_sequences() -> None:
    failed = extract_failed_test_lines(
        "\x1b[31mFAILED tests/test_alpha.py::test_one - AssertionError\x1b[0m"
    )
    assert failed == ["tests/test_alpha.py::test_one"]


def test_live_rows_include_progress_from_pytest_percentage() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    reporter.capture_output_line("other", "test_file.py .................... [ 37%]")

    row = reporter.live_rows()[0]
    assert row["progress"] == "37.00%"


def test_console_presenter_suppresses_lane_stream_output_by_default(capsys) -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    presenter = LaneConsolePresenter(reporter)

    presenter.emit_lane_line("other", "hello from lane\n")

    assert capsys.readouterr().out == ""


def test_console_presenter_delegates_to_display_strategy() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])

    calls: list[tuple[str, Any]] = []

    class FakeDisplay:
        def start(self) -> None:
            calls.append(("start", None))

        def stop(self) -> None:
            calls.append(("stop", None))

        def print_summary(
            self, summary_reporter: LaneProgressReporter, wall_seconds: float
        ) -> None:
            calls.append(("print_summary", (summary_reporter, wall_seconds)))

        def emit_lane_line(self, lane_name: str, line: str) -> None:
            calls.append(("emit_lane_line", (lane_name, line)))

        def refresh(self) -> None:
            calls.append(("refresh", None))

    def build_fake_display(
        _reporter: LaneProgressReporter, _show_lane_stream: bool
    ) -> FakeDisplay:
        return FakeDisplay()

    presenter = LaneConsolePresenter(reporter, display_factory=build_fake_display)

    presenter.start()
    presenter.emit_lane_line("other", "line\n")
    presenter.refresh()
    presenter.print_summary(reporter, wall_seconds=1.5)
    presenter.stop()

    assert calls == [
        ("start", None),
        ("emit_lane_line", ("other", "line\n")),
        ("refresh", None),
        ("print_summary", (reporter, 1.5)),
        ("stop", None),
    ]


def test_console_presenter_defaults_to_plain_display_when_rich_unavailable(
    monkeypatch,
) -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])

    init_calls: list[tuple[LaneProgressReporter, bool]] = []

    class FakePlainDisplay:
        def __init__(
            self, summary_reporter: LaneProgressReporter, show_lane_stream: bool
        ) -> None:
            init_calls.append((summary_reporter, show_lane_stream))

        def start(self) -> None:
            return

        def stop(self) -> None:
            return

        def print_summary(
            self, summary_reporter: LaneProgressReporter, wall_seconds: float
        ) -> None:
            return

        def emit_lane_line(self, lane_name: str, line: str) -> None:
            return

        def refresh(self) -> None:
            return

    class FakeRichDisplay:
        def __init__(
            self, summary_reporter: LaneProgressReporter, show_lane_stream: bool
        ) -> None:
            raise AssertionError("rich strategy should not be selected")

    monkeypatch.setattr(lane_reporter, "HAS_RICH", False)
    monkeypatch.setattr(lane_reporter, "PlainLaneDisplay", FakePlainDisplay)
    monkeypatch.setattr(lane_reporter, "RichLaneDisplay", FakeRichDisplay)

    presenter = LaneConsolePresenter(reporter, show_lane_stream=True)

    assert isinstance(presenter._display, FakePlainDisplay)
    assert init_calls == [(reporter, True)]


def test_console_presenter_defaults_to_rich_display_when_rich_available(
    monkeypatch,
) -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])

    init_calls: list[tuple[LaneProgressReporter, bool]] = []

    class FakeRichDisplay:
        def __init__(
            self, summary_reporter: LaneProgressReporter, show_lane_stream: bool
        ) -> None:
            init_calls.append((summary_reporter, show_lane_stream))

        def start(self) -> None:
            return

        def stop(self) -> None:
            return

        def print_summary(
            self, summary_reporter: LaneProgressReporter, wall_seconds: float
        ) -> None:
            return

        def emit_lane_line(self, lane_name: str, line: str) -> None:
            return

        def refresh(self) -> None:
            return

    class FakePlainDisplay:
        def __init__(
            self, summary_reporter: LaneProgressReporter, show_lane_stream: bool
        ) -> None:
            raise AssertionError("plain strategy should not be selected")

    monkeypatch.setattr(lane_reporter, "HAS_RICH", True)
    monkeypatch.setattr(lane_reporter, "PlainLaneDisplay", FakePlainDisplay)
    monkeypatch.setattr(lane_reporter, "RichLaneDisplay", FakeRichDisplay)

    presenter = LaneConsolePresenter(reporter, show_lane_stream=False)

    assert isinstance(presenter._display, FakeRichDisplay)
    assert init_calls == [(reporter, False)]


def test_rich_display_builds_bordered_table() -> None:
    if not lane_reporter.HAS_RICH:
        pytest.skip("rich is not installed")

    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    reporter.mark_finished("other", exit_code=0)

    display = lane_reporter.RichLaneDisplay(reporter)
    table = display._build_table()

    assert getattr(table, "show_edge", False) is True


def test_capture_output_line_accumulates_passed_and_skipped_from_progress_dots() -> (
    None
):
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    reporter.capture_output_line("other", "tests/test_foo.py ..s...  [ 20%]")
    reporter.capture_output_line("other", "tests/test_bar.py ......  [ 40%]")

    row = reporter.live_rows()[0]
    assert row["passed"] == "11"  # 5 dots + 6 dots
    assert row["skipped"] == "1"  # 1 s


def test_capture_output_line_final_summary_overrides_dot_counts() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    reporter.capture_output_line("other", "tests/test_foo.py ..s...  [ 50%]")
    # final summary overrides dot-counted values
    reporter.capture_output_line("other", "===== 4 passed, 1 skipped in 1.0s =====")

    row = reporter.live_rows()[0]
    assert row["passed"] == "4"
    assert row["skipped"] == "1"


def test_capture_output_line_does_not_count_dots_from_filename() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    # Filename ends with .py but the last token before [XX%] is the result chars only
    reporter.capture_output_line("other", "tests/test_session.py ..s.  [ 10%]")

    row = reporter.live_rows()[0]
    assert row["passed"] == "3"
    assert row["skipped"] == "1"


def test_summary_includes_aggregate_totals() -> None:
    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["postgres", "other"])
    reporter.mark_started("postgres")
    reporter.mark_started("other")

    reporter.capture_output_line("postgres", "collected 5 items")
    reporter.capture_output_line("postgres", "===== 4 passed, 1 skipped in 0.5s =====")
    reporter.mark_finished("postgres", exit_code=0)

    reporter.capture_output_line("other", "collected 3 items")
    reporter.capture_output_line(
        "other", "FAILED tests/test_x.py::test_fail - AssertionError"
    )
    reporter.capture_output_line("other", "===== 2 passed in 0.3s =====")
    reporter.mark_finished("other", exit_code=1)

    summary = reporter.build_summary(wall_seconds=1.0)

    assert "Total: 8 collected | 6 passed | 1 failed | 1 skipped" in summary


def test_capture_output_line_extracts_collected_count() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    reporter.capture_output_line("other", "collected 12 items")

    row = reporter.live_rows()[0]
    assert row["collected"] == "12"


def test_capture_output_line_extracts_passed_and_skipped_from_summary() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")

    reporter.capture_output_line("other", "===== 8 passed, 2 skipped in 1.23s =====")

    row = reporter.live_rows()[0]
    assert row["passed"] == "8"
    assert row["skipped"] == "2"


def test_live_rows_include_collected_passed_failed_skipped() -> None:
    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["postgres"])
    reporter.mark_started("postgres")

    reporter.capture_output_line("postgres", "collected 10 items")
    reporter.capture_output_line(
        "postgres", "FAILED tests/test_a.py::test_one - AssertionError: boom"
    )
    reporter.capture_output_line(
        "postgres", "===== 1 failed, 7 passed, 2 skipped in 0.50s ====="
    )
    reporter.mark_finished("postgres", exit_code=1)

    row = reporter.live_rows()[0]
    assert row["collected"] == "10"
    assert row["passed"] == "7"
    assert row["failed"] == "1"
    assert row["skipped"] == "2"


def test_rich_table_has_collected_passed_failed_skipped_columns() -> None:
    if not lane_reporter.HAS_RICH:
        pytest.skip("rich is not installed")

    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    reporter.mark_finished("other", exit_code=0)

    display = lane_reporter.RichLaneDisplay(reporter)
    table = display._build_table()

    column_names = [col.header for col in table.columns]
    assert "Collected" in column_names
    assert "Passed" in column_names
    assert "Failed" in column_names
    assert "Skipped" in column_names


def test_rich_display_print_summary_adds_blank_line_before_title(monkeypatch) -> None:
    if not lane_reporter.HAS_RICH:
        pytest.skip("rich is not installed")

    reporter = LaneProgressReporter(clock=lambda: 100.0)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    reporter.mark_finished("other", exit_code=0)

    printed: list[str | None] = []

    class FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            if not args:
                printed.append(None)
                return
            printed.append(str(args[0]))

    monkeypatch.setattr(lane_reporter, "new_console", FakeConsole)

    display = lane_reporter.RichLaneDisplay(reporter)
    display.print_summary(reporter, wall_seconds=1.0)

    assert printed[0] == ""
    assert printed[1] == f"[bold cyan]{SUMMARY_TITLE}[/]"


def test_summary_prints_reproduce_hint_for_each_failed_lane() -> None:
    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["postgres", "other"])
    reporter.mark_started("postgres")
    reporter.mark_started("other")
    reporter.mark_finished("postgres", exit_code=1)
    reporter.mark_finished("other", exit_code=0)

    summary = reporter.build_summary(wall_seconds=1.0)

    assert "reproduce: pytest --lane=postgres" in summary
    assert "reproduce: pytest --lane=other" not in summary


def test_rich_summary_prints_reproduce_hint_for_failed_lane(monkeypatch) -> None:
    if not lane_reporter.HAS_RICH:
        pytest.skip("rich is not installed")

    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["postgres"])
    reporter.mark_started("postgres")
    reporter.mark_finished("postgres", exit_code=1)

    printed: list[str] = []

    class FakeConsole:
        def print(self, *args: object, **kwargs: object) -> None:
            printed.append(str(args[0]) if args else "")

    monkeypatch.setattr(lane_reporter, "new_console", FakeConsole)

    display = lane_reporter.RichLaneDisplay(reporter)
    display.print_summary(reporter, wall_seconds=1.0)

    assert any("reproduce:" in line and "--lane=postgres" in line for line in printed)


def test_reproduce_overrides_print_every_line_for_failed_shards() -> None:
    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(
        ["postgres~1of2"],
        reproduce_overrides={
            "postgres~1of2": (
                "pytest --lane=postgres",
                "pytest db/test_a.py db/test_b.py",
            )
        },
    )
    reporter.mark_started("postgres~1of2")
    reporter.mark_finished("postgres~1of2", exit_code=1)

    summary = reporter.build_summary(wall_seconds=1.0)

    assert "reproduce: pytest --lane=postgres" in summary
    assert "or: pytest db/test_a.py db/test_b.py" in summary
    assert "reproduce: pytest --lane=postgres~1of2" not in summary


def _reporter_at_half_progress_with_20s_remaining() -> LaneProgressReporter:
    now = {"value": 10.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(clock=fake_clock)
    reporter.register_lanes(["other"])
    reporter.mark_started("other")
    now["value"] = 30.0
    reporter.capture_output_line("other", "test_file.py .................... [ 50%]")
    return reporter


def test_estimated_remaining_includes_pending_lanes_with_recorded_durations() -> None:
    now = {"value": 10.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(
        clock=fake_clock, expected_durations={"queued_db": 30.0}
    )
    reporter.register_lanes(["running_lane", "queued_db"])
    reporter.mark_started("running_lane")
    now["value"] = 30.0
    reporter.capture_output_line(
        "running_lane", "test_file.py .................... [ 50%]"
    )

    remaining = reporter.estimated_remaining_seconds()

    # 20s left on the running lane plus the queued lane's recorded 30s.
    assert remaining == 50.0


def test_pending_lanes_without_recorded_durations_do_not_inflate_the_estimate() -> None:
    now = {"value": 10.0}

    def fake_clock() -> float:
        return now["value"]

    reporter = LaneProgressReporter(clock=fake_clock)
    reporter.register_lanes(["running_lane", "queued_unknown"])
    reporter.mark_started("running_lane")
    now["value"] = 30.0
    reporter.capture_output_line(
        "running_lane", "test_file.py .................... [ 50%]"
    )

    assert reporter.estimated_remaining_seconds() == 20.0


def test_plain_snapshot_header_includes_estimated_time_remaining(capsys) -> None:
    reporter = _reporter_at_half_progress_with_20s_remaining()
    display = lane_reporter.PlainLaneDisplay(reporter)

    display.refresh()

    assert "Lane status snapshot (eta 20.00s)" in capsys.readouterr().out


def test_rich_table_caption_shows_estimated_time_remaining() -> None:
    if not lane_reporter.HAS_RICH:
        pytest.skip("rich is not installed")

    reporter = _reporter_at_half_progress_with_20s_remaining()
    display = lane_reporter.RichLaneDisplay(reporter)

    table = display._build_table()

    assert "eta 20.00s" in str(table.caption)
