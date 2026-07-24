"""pytest hook implementations for the lane orchestrator.

When the package is installed, the hooks load through the ``pytest11`` entry
point (:mod:`pytest_lanes.plugin`). Vendored copies can re-export them from a
repo-root ``conftest.py`` instead. Lane configuration is loaded once per
session from the host project's INI file and cached on module state.

Responsibilities, in order:

* register the ``--lanes-full``, ``--lane``, and ``--lanes-max-workers`` CLI
  options;
* in :func:`pytest_cmdline_main`, intercept the command line and fan out into
  lane subprocesses when :func:`~pytest_lanes.mode.orchestration_mode`
  selects a multi-lane mode;
* apply per-lane env overrides (``subprocess_env_set``) around every test in
  single-process mode (:func:`pytest_runtest_setup` /
  :func:`pytest_runtest_teardown`);
* in :func:`pytest_collection_modifyitems`, mark each item with its lane's
  marker and skip items outside any ``--lane=`` selection.

When no ``[pytest-lanes]`` configuration exists in the rootdir, every hook is
a no-op and pytest behaves as if the plugin were not installed.
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path

import pytest

from pytest_lanes.adhoc import resolve_lane_config_or_none
from pytest_lanes.config import LaneConfig
from pytest_lanes.constants import (
    CHILD_DURATIONS_OUT_ENV,
    TEST_ORCHESTRATION_CHILD_ENV,
    XDIST_WORKER_ENV,
)
from pytest_lanes.durations import duration_store_for_rootdir
from pytest_lanes.executor import run_lane_commands
from pytest_lanes.explain import format_lane_explanation
from pytest_lanes.invocation import (
    invocation_args,
    passthrough_args_for_lanes,
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
from pytest_lanes.suggest import (
    format_lane_suggestion,
    format_split_advice,
    scan_project,
)

ENV_OVERRIDE_ATTR = "_pytest_lanes_env_overrides"

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


def _load_lane_config_for(config: pytest.Config) -> LaneConfig | None:
    return resolve_lane_config_or_none(
        cli_definitions=tuple(config.getoption("--lane-def") or ()),
        lanes_auto=bool(config.getoption("--lanes-auto")),
        rootpath=Path(str(config.rootpath)),
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
            "Comma-separated for multiple lanes, e.g. --lane=postgres,timescale."
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
            "plus a fallback for stray files — no config file needed."
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


def pytest_cmdline_main(config: pytest.Config) -> int | None:
    is_child_process = os.environ.get(TEST_ORCHESTRATION_CHILD_ENV) == "1"
    if config.getoption("--lanes-suggest") and not is_child_process:
        rootpath = Path(str(config.rootpath))
        print(format_lane_suggestion(scan_project(rootpath)))
        advice = format_split_advice(
            duration_store_for_rootdir(rootpath).recorded_lane_records()
        )
        if advice:
            print(f"\n{advice}")
        return 0

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
    commands = build_lane_commands(
        mode=mode, passthrough_args=passthrough, lane_config=lane_config
    )
    if not commands:
        # Lanes are declared but no subprocess order list is: there is nothing
        # to fan out, so let pytest run normally instead of exiting early.
        return None
    max_workers = resolve_max_workers(
        cli_value=config.getoption("--lanes-max-workers"),
        config_value=lane_config.max_workers,
        detected=detected_cpu_count(),
    )
    return run_lane_commands(
        commands,
        max_workers=max_workers,
        duration_store=duration_store_for_rootdir(Path(str(config.rootpath))),
    )


def pytest_configure(config: pytest.Config) -> None:
    """Load lane config and, for ``--lane=<name>`` runs, restrict collection.

    Runs before any collection, so config rewrites here are picked up by
    pytest's collector. When ``--lane=<name>`` is set we replace
    ``config.args`` with the lane's subprocess paths and extend
    ``config.option.ignore`` with the lane's ignores — otherwise pytest
    would try to collect every file under rootdir and fail on imports
    from unrelated lanes whose dependencies are not installed in this env.
    """
    global _lane_config, _rootpath

    _rootpath = Path(str(config.rootpath))
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
    merged_ignore: list[str] = list(existing_ignore)
    seen = set(existing_ignore)
    for ignore_path in ignores:
        if ignore_path in seen:
            continue
        seen.add(ignore_path)
        merged_ignore.append(ignore_path)
    config.option.ignore = merged_ignore


def pytest_sessionstart(session: pytest.Session) -> None:
    """In lane children, start measuring the run when the executor asks.

    The executor sets :data:`CHILD_DURATIONS_OUT_ENV` to a JSON output path
    per child; without it (in-process runs, foreign projects) this is a
    no-op.
    """
    global _child_recorder

    output_path = os.environ.get(CHILD_DURATIONS_OUT_ENV)
    if not output_path:
        return
    if os.environ.get(XDIST_WORKER_ENV):
        # In-lane xdist: only the lane's controller process records — it
        # receives every worker's test reports; workers racing on the same
        # output file would corrupt it.
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


@pytest.hookimpl(tryfirst=True)
def pytest_runtestloop(session: pytest.Session) -> bool | None:
    """Skip test execution entirely for ``--lanes-explain`` runs.

    Returning ``True`` short-circuits pytest's run loop after collection —
    the same mechanism ``--collect-only`` uses — without triggering the
    terminal reporter's collect-only tree output.
    """
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

    try:
        spec = lane_for_item(item, _rootpath, _lane_config)
    except LookupError:
        return ()
    return tuple(spec.subprocess_env_set)
