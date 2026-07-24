"""Integration-style tests for the orchestration dispatch path.

These exercise the ``pytest_cmdline_main`` wiring: orchestration_mode →
build_lane_commands → run_lane_commands. The lane config itself comes from
the in-memory example builder used by ``test_lane_assignment``, so we
do not depend on a real ``pytest.ini``.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from pytest_lanes import hooks
from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV
from tests.test_lane_assignment import _example_lane_config


class _FakeConfig:
    def __init__(
        self,
        rootpath: Path,
        full: bool = False,
        lane: str | None = None,
        invocation_args: tuple[str, ...] = (),
        max_workers: int | None = None,
    ) -> None:
        self.rootpath = rootpath
        self._full = full
        self._lane = lane
        self._max_workers = max_workers
        self.invocation_params = type("InvocationParams", (), {"args": invocation_args})

    def getoption(self, option_name: str) -> object:
        if option_name == "--lanes-full":
            return self._full
        if option_name == "--lane":
            return self._lane
        if option_name == "--lanes-max-workers":
            return self._max_workers
        return False


def _without_child_env_var():
    return patch.dict(os.environ, {TEST_ORCHESTRATION_CHILD_ENV: ""}, clear=False)


def test_targeted_path_returns_none_and_does_not_call_run_lane_commands() -> None:
    config = _FakeConfig(
        rootpath=Path("C:/repo"),
        invocation_args=("tests/something.py",),
    )

    with (
        patch.object(hooks, "run_lane_commands") as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result is None
    mock_run.assert_not_called()


def test_plain_pytest_dot_dispatches_five_standard_lanes() -> None:
    config = _FakeConfig(rootpath=Path("C:/repo"), invocation_args=(".",))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    dispatched_commands = mock_run.call_args.args[0]
    assert [command.name for command in dispatched_commands] == [
        "postgres",
        "timescale",
        "acceptance",
        "http_adapter",
        "other",
    ]


def test_full_flag_dispatches_six_lanes_including_full_build_verification() -> None:
    config = _FakeConfig(
        rootpath=Path("C:/repo"), full=True, invocation_args=(".", "--lanes-full", "-q")
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    dispatched_commands = mock_run.call_args.args[0]
    assert [command.name for command in dispatched_commands] == [
        "postgres",
        "timescale",
        "acceptance",
        "full_build_verification",
        "http_adapter",
        "other",
    ]


def test_full_build_verification_lane_propagates_env_set_into_command() -> None:
    config = _FakeConfig(
        rootpath=Path("C:/repo"), full=True, invocation_args=(".", "--lanes-full")
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        hooks.pytest_cmdline_main(config)

    dispatched_commands = mock_run.call_args.args[0]
    fbv = next(c for c in dispatched_commands if c.name == "full_build_verification")
    assert ("BUILD_OUTPUT_DIR", "build/full-build-verification") in fbv.env_set


def test_detected_cpu_count_bounds_lane_concurrency_by_default() -> None:
    config = _FakeConfig(rootpath=Path("C:/repo"), invocation_args=(".",))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
        patch.object(hooks, "detected_cpu_count", return_value=8),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["max_workers"] == 8


def test_cli_max_workers_flag_overrides_the_detected_default() -> None:
    config = _FakeConfig(
        rootpath=Path("C:/repo"), invocation_args=(".",), max_workers=3
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
        patch.object(hooks, "detected_cpu_count", return_value=8),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["max_workers"] == 3


def test_ini_max_workers_is_used_when_no_cli_flag_is_passed() -> None:
    config = _FakeConfig(rootpath=Path("C:/repo"), invocation_args=(".",))
    lane_config = replace(_example_lane_config(), max_workers=4)

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(hooks, "_load_lane_config_for", return_value=lane_config),
        patch.object(hooks, "detected_cpu_count", return_value=8),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["max_workers"] == 4
