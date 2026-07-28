"""Give every lane its own report files, then aggregate them for the user."""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from pytest_lanes.coverage_support import (
    args_without_coverage_reports,
    coverage_report_command,
    is_coverage_requested,
    lane_coverage_env,
    requested_coverage_reports,
)
from pytest_lanes.lanes import LaneCommand
from pytest_lanes.report_merge import (
    JunitMergeError,
    args_with_lane_junit_path,
    junit_target_path,
    lane_junit_path,
    merged_junit_document,
)

# pytest-cov reads an empty report spec as "measure, report nothing"; honour it.
_NO_REPORT_SPEC = ""
_SUPPRESS_CHILD_REPORTS = "--cov-report="
_COVERAGE_MODULE = "coverage"
_COMBINE_COMMAND = "combine"


@dataclass(frozen=True)
class LaneReportPlan:
    """What the parent owes the user once the lanes have finished."""

    staging_dir: Path
    junit_target: str | None = None
    coverage_requested: bool = False
    coverage_reports: tuple[str, ...] = ()

    @property
    def has_work(self) -> bool:
        return self.junit_target is not None or self.coverage_requested


def prepare_lane_reports(
    commands: Sequence[LaneCommand], staging_dir: Path
) -> tuple[list[LaneCommand], LaneReportPlan]:
    """Redirect each lane's report output into ``staging_dir``."""
    requested_args = commands[0].args if commands else ()
    plan = LaneReportPlan(
        staging_dir=staging_dir,
        junit_target=junit_target_path(requested_args),
        coverage_requested=is_coverage_requested(requested_args),
        coverage_reports=tuple(
            report
            for report in requested_coverage_reports(requested_args)
            if report != _NO_REPORT_SPEC
        ),
    )
    if not plan.has_work:
        return list(commands), plan
    return [_prepared(command, plan) for command in commands], plan


def _prepared(command: LaneCommand, plan: LaneReportPlan) -> LaneCommand:
    args = command.args
    env_set = command.env_set
    if plan.junit_target is not None:
        args = args_with_lane_junit_path(args, command.name, plan.staging_dir)
    if plan.coverage_requested:
        args = (*args_without_coverage_reports(args), _SUPPRESS_CHILD_REPORTS)
        env_set = (*env_set, *lane_coverage_env(command.name, plan.staging_dir))
    return replace(command, args=args, env_set=env_set)


def aggregate_lane_reports(plan: LaneReportPlan, lane_names: Iterable[str]) -> None:
    """Fold the staged per-lane reports into the artifacts the user asked for."""
    if plan.junit_target is not None:
        _merge_junit_reports(plan, lane_names)
    if plan.coverage_requested:
        _combine_coverage(plan)


def _merge_junit_reports(plan: LaneReportPlan, lane_names: Iterable[str]) -> None:
    documents = [
        path.read_text(encoding="utf-8")
        for path in (lane_junit_path(name, plan.staging_dir) for name in lane_names)
        if path.exists()
    ]
    if not documents:
        return
    try:
        merged = merged_junit_document(documents)
    except JunitMergeError as error:
        print(f"pytest-lanes: could not merge lane JUnit reports: {error}")
        return
    target = Path(plan.junit_target or "")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(merged, encoding="utf-8")


def _combine_coverage(plan: LaneReportPlan) -> None:
    if not _run_coverage((_COMBINE_COMMAND, str(plan.staging_dir))):
        return
    for report in plan.coverage_reports:
        command = coverage_report_command(report)
        if command is None:
            # An unsupported spec is reported, never silently dropped.
            print(
                f"pytest-lanes: coverage report '{report}' is not supported "
                "for lane runs; the combined data file was still written."
            )
            continue
        _run_coverage(command)


def _run_coverage(arguments: tuple[str, ...]) -> bool:
    completed = subprocess.run(
        [sys.executable, "-m", _COVERAGE_MODULE, *arguments],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        print(
            f"pytest-lanes: coverage {arguments[0]} failed "
            f"({completed.returncode}): {(completed.stderr or '').strip()}"
        )
        return False
    if completed.stdout:
        print(completed.stdout.rstrip())
    return True
