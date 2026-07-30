"""pytest hook implementations for the lane orchestrator."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from pytest_lanes.adhoc import resolve_lane_config_or_none
from pytest_lanes.balance import balanced_partition, format_balanced_suggestion
from pytest_lanes.config import LaneConfig
from pytest_lanes.constants import (
    CHILD_DURATIONS_OUT_ENV,
    XDIST_WORKER_ENV,
    is_lane_child,
)
from pytest_lanes.durations import duration_store_for_rootdir
from pytest_lanes.executor import run_lane_commands
from pytest_lanes.explain import format_lane_explanation
from pytest_lanes.invocation import (
    invocation_args,
    passthrough_args_for_lanes,
    wants_live_lane_output,
)
from pytest_lanes.lane_selection import (
    apply_lane_filter,
    collection_args_for_lanes,
    parse_lane_selection,
    validate_lane_names,
)
from pytest_lanes.lanes import build_lane_commands, explain_lane_for_item, lane_for_item
from pytest_lanes.mode import orchestration_mode
from pytest_lanes.recording import ChildRunRecorder
from pytest_lanes.scheduler import detected_cpu_count, resolve_max_workers
from pytest_lanes.sharding import (
    ShardPlan,
    load_persisted_plan,
    persist_first_shard,
    plan_shards,
    shard_plan_path_for_rootdir,
)
from pytest_lanes.suggest import (
    format_lane_suggestion,
    format_split_advice,
    scan_project,
)

ENV_OVERRIDE_ATTR = "_pytest_lanes_env_overrides"
# Past this cap, per-lane fixed costs eat the marginal parallelism.
MAX_SUGGESTED_LANES = 8

_lane_config: LaneConfig | None = None
_rootpath: Path | None = None
_child_recorder: ChildRunRecorder | None = None


def _xdist_is_available() -> bool:
    return importlib.util.find_spec("xdist") is not None


def _ensure_xdist_available_for(lane_config: LaneConfig) -> None:
    lanes_needing_xdist = [
        spec.name for spec in lane_config.lanes if spec.lane_numprocesses is not None
    ]
    if not lanes_needing_xdist or _xdist_is_available():
        return
    raise pytest.UsageError(
        "lane_numprocesses is set on lane(s) "
        f"{', '.join(lanes_needing_xdist)} but pytest-xdist is not installed. "
        "Install it (pip install pytest-xdist) or remove the setting."
    )


def _rootpath_of(config: pytest.Config) -> Path:
    return Path(str(config.rootpath))


def _load_lane_config_for(config: pytest.Config) -> LaneConfig | None:
    return resolve_lane_config_or_none(
        cli_definitions=tuple(config.getoption("--lane-def") or ()),
        lanes_auto=bool(config.getoption("--lanes-auto")),
        rootpath=_rootpath_of(config),
    )


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("lanes", "lane-based subprocess orchestration")
    group.addoption(
        "--lanes-full",
        action="store_true",
        default=False,
        help="Run every lane, including those only listed in subprocess_order_full.",
    )
    group.addoption(
        "--lane",
        action="store",
        default=None,
        help=(
            "Run only the named lane(s) in-process (no subprocess fanout). "
            "Comma-separated for multiple lanes, e.g. --lane=postgres,redis."
        ),
    )
    group.addoption(
        "--lanes-max-workers",
        action="store",
        type=int,
        default=None,
        help=(
            "Maximum lane subprocesses running concurrently; remaining lanes "
            "queue in declared order (default: CPU count)."
        ),
    )
    group.addoption(
        "--lanes-explain",
        action="store_true",
        default=False,
        help=(
            "List each collected test, its lane, and the classifier rule "
            "that claimed it, then exit without running any tests."
        ),
    )
    group.addoption(
        "--lane-def",
        action="append",
        default=None,
        metavar="NAME=PATH[,PATH...]",
        help=(
            "Define a lane on the command line (repeatable), no config file "
            "needed. Takes precedence over INI lanes; ad-hoc lanes apply no "
            "markers."
        ),
    )
    group.addoption(
        "--lanes-auto",
        action="store_true",
        default=False,
        help=(
            "Derive one lane per test-bearing subdirectory of the rootdir, "
            "plus a fallback for stray files; no config file needed."
        ),
    )
    group.addoption(
        "--lanes-suggest",
        action="store_true",
        default=False,
        help=(
            "Statically analyze the suite (directory layout, conftest "
            "fixtures and imports) and print a suggested [pytest-lanes] "
            "INI config to review, then exit without running any tests."
        ),
    )
    group.addoption(
        "--lanes-no-shard",
        action="store_true",
        default=False,
        help="Disable shard planning for this run; lanes run whole.",
    )
    group.addoption(
        "--lanes-show-output",
        action="store_true",
        default=False,
        help=(
            "Stream every lane's raw output live instead of showing it only "
            "for failed lanes. Implied by -s / --capture=no."
        ),
    )


def pytest_cmdline_main(config: pytest.Config) -> int | None:
    if config.getoption("--lanes-suggest") and not is_lane_child():
        return _print_suggestion(_rootpath_of(config))

    mode = orchestration_mode(config)
    if mode is None:
        return None

    lane_config = _load_lane_config_for(config)
    if lane_config is None:
        if config.getoption("--lanes-auto"):
            print(
                "pytest-lanes: --lanes-auto found no test-bearing "
                "subdirectory partition; running plain pytest."
            )
        return None

    _ensure_xdist_available_for(lane_config)

    args = invocation_args(config)
    passthrough = passthrough_args_for_lanes(args)
    max_workers = resolve_max_workers(
        cli_value=config.getoption("--lanes-max-workers"),
        config_value=lane_config.max_workers,
        detected=detected_cpu_count(),
    )
    rootpath = _rootpath_of(config)
    duration_store = duration_store_for_rootdir(rootpath)
    # -s is a request to see output now; honour it like the explicit flag.
    show_lane_output = bool(
        config.getoption("--lanes-show-output")
    ) or wants_live_lane_output(args)

    if config.getoption("--lanes-no-shard"):
        plan_path = None
        plan = ShardPlan(
            commands=tuple(
                build_lane_commands(
                    mode=mode, passthrough_args=passthrough, lane_config=lane_config
                )
            )
        )
    else:
        plan_path = shard_plan_path_for_rootdir(rootpath)
        plan = plan_shards(
            mode=mode,
            passthrough_args=passthrough,
            lane_config=lane_config,
            records=duration_store.recorded_lane_records(),
            max_workers=max_workers,
            file_exists=lambda relative: (rootpath / relative).exists(),
            persisted_plan=load_persisted_plan(plan_path),
        )

    if not plan.commands:
        # Lanes without a subprocess order: nothing to fan out, run normally.
        return None
    for note in plan.notes:
        print(f"pytest-lanes: {note}")
    if plan.sharded_lane and plan_path is not None:
        persist_first_shard(plan_path, plan.sharded_lane, plan.first_shard_files)

    return run_lane_commands(
        list(plan.commands),
        max_workers=max_workers,
        duration_store=duration_store,
        shard_parents=dict(plan.shard_parents) or None,
        reproduce_overrides=dict(plan.reproduce_lines) or None,
        show_lane_output=show_lane_output,
    )


def _print_suggestion(rootpath: Path) -> int:
    records = duration_store_for_rootdir(rootpath).recorded_lane_records()
    balanced = balanced_partition(
        records, lane_count=min(detected_cpu_count(), MAX_SUGGESTED_LANES)
    )
    if balanced:
        # With recorded durations, propose a partition that finishes evenly.
        print(format_balanced_suggestion(balanced))
        return 0

    print(format_lane_suggestion(scan_project(rootpath)))
    advice = format_split_advice(records)
    if advice:
        print(f"\n{advice}")
    print(
        "\nTip: run once with a lane config (--lanes-auto or the block "
        "above) so per-file durations are recorded; --lanes-suggest then "
        "proposes a duration-balanced partition."
    )
    return 0


def pytest_configure(config: pytest.Config) -> None:
    """Load lane config and, for ``--lane=<name>`` runs, restrict collection."""
    global _lane_config, _rootpath

    _rootpath = _rootpath_of(config)
    _lane_config = _load_lane_config_for(config)

    selected = parse_lane_selection(config.getoption("--lane", default=None))
    if not selected:
        return

    if _lane_config is None:
        raise pytest.UsageError(
            "--lane was passed but no [pytest-lanes] configuration was found "
            "in pytest.ini, tox.ini, or setup.cfg at the rootdir."
        )

    validate_lane_names(selected, _lane_config)
    positional, ignores = collection_args_for_lanes(selected, _lane_config)

    if positional:
        config.args = positional
        if hasattr(config.option, "file_or_dir"):
            config.option.file_or_dir = list(positional)

    existing_ignore = list(getattr(config.option, "ignore", None) or [])
    config.option.ignore = list(dict.fromkeys([*existing_ignore, *ignores]))


def pytest_sessionstart(session: pytest.Session) -> None:
    """In lane children, start measuring the run when the executor asks."""
    global _child_recorder

    output_path = os.environ.get(CHILD_DURATIONS_OUT_ENV)
    if not output_path:
        return
    if os.environ.get(XDIST_WORKER_ENV):
        # In-lane xdist: only the controller records; racing workers would corrupt the file.
        return
    _child_recorder = ChildRunRecorder(output_path=Path(output_path))
    _child_recorder.mark_session_start()


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if _child_recorder is not None:
        _child_recorder.add_report_duration(report.nodeid, report.duration)


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if _child_recorder is not None:
        _child_recorder.write()


def pytest_collection_finish(session: pytest.Session) -> None:
    """Print the lane-classification listing when ``--lanes-explain`` is set."""
    if _child_recorder is not None:
        _child_recorder.mark_collection_finished()

    if not session.config.getoption("--lanes-explain"):
        return

    if _lane_config is None or _rootpath is None:
        raise pytest.UsageError(
            "--lanes-explain was passed but no [pytest-lanes] configuration "
            "was found in pytest.ini, tox.ini, or setup.cfg at the rootdir."
        )

    entries = [
        (item.nodeid, explain_lane_for_item(item, _rootpath, _lane_config))
        for item in session.items
    ]
    print(format_lane_explanation(entries))
    _print_divisibility_footer(_lane_config, _rootpath)


def _print_divisibility_footer(lane_config: LaneConfig, rootpath: Path) -> None:
    divisible_names = [spec.name for spec in lane_config.lanes if spec.divisible]
    if not divisible_names:
        return
    print(f"Divisible lanes: {', '.join(divisible_names)}")
    persisted = load_persisted_plan(shard_plan_path_for_rootdir(rootpath))
    if persisted is None:
        return
    lane_name, first_shard_files = persisted
    print(
        f"Persisted shard plan: {lane_name} -> shard 1: "
        f"{' '.join(first_shard_files)}; shard 2: remainder"
    )


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Skip test execution entirely for ``--lanes-explain`` runs."""
    if session.config.getoption("--lanes-explain"):
        return True
    return None


def pytest_runtest_setup(item: pytest.Item) -> None:
    if _child_recorder is not None:
        _child_recorder.mark_test_started()

    env_overrides = _env_overrides_for_item(item)
    if not env_overrides:
        return

    saved: dict[str, str | None] = {}
    for key, value in env_overrides:
        saved[key] = os.environ.get(key)
        os.environ[key] = value
    setattr(item, ENV_OVERRIDE_ATTR, saved)


def pytest_runtest_teardown(item: pytest.Item, nextitem: pytest.Item | None) -> None:
    saved = getattr(item, ENV_OVERRIDE_ATTR, None)
    if saved is None:
        return

    for key, previous_value in saved.items():
        if previous_value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = previous_value


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    if _lane_config is None or _rootpath is None:
        return

    selected = parse_lane_selection(config.getoption("--lane"))
    apply_lane_filter(
        items=items,
        rootpath=_rootpath,
        lane_config=_lane_config,
        selected_lanes=selected,
        marker_factory=lambda name: getattr(pytest.mark, name),
    )


def _env_overrides_for_item(item: pytest.Item) -> tuple[tuple[str, str], ...]:
    if _lane_config is None or _rootpath is None:
        return ()
    if not any(spec.subprocess_env_set for spec in _lane_config.lanes):
        return ()

    try:
        spec = lane_for_item(item, _rootpath, _lane_config)
    except LookupError:
        return ()
    return tuple(spec.subprocess_env_set)
