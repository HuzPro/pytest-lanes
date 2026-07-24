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
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from pytest_lanes import hooks
from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV
from tests.test_lane_assignment import _example_lane_config, _FakeItem


class _FakeConfig:
    def __init__(
        self,
        rootpath: Path,
        full: bool = False,
        lane: str | None = None,
        invocation_args: tuple[str, ...] = (),
        max_workers: int | None = None,
        explain: bool = False,
        lane_defs: list[str] | None = None,
        lanes_auto: bool = False,
        suggest: bool = False,
    ) -> None:
        self.rootpath = rootpath
        self._full = full
        self._lane = lane
        self._max_workers = max_workers
        self._explain = explain
        self._lane_defs = lane_defs
        self._lanes_auto = lanes_auto
        self._suggest = suggest
        self.invocation_params = type("InvocationParams", (), {"args": invocation_args})

    def getoption(self, option_name: str) -> object:
        if option_name == "--lanes-full":
            return self._full
        if option_name == "--lane":
            return self._lane
        if option_name == "--lanes-max-workers":
            return self._max_workers
        if option_name == "--lanes-explain":
            return self._explain
        if option_name == "--lane-def":
            return self._lane_defs
        if option_name == "--lanes-auto":
            return self._lanes_auto
        if option_name == "--lanes-suggest":
            return self._suggest
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


def test_lane_defs_fan_out_without_any_ini_config(tmp_path: Path) -> None:
    config = _FakeConfig(
        rootpath=tmp_path,
        invocation_args=(".", "--lane-def", "db=tests/db"),
        lane_defs=["db=tests/db"],
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    dispatched_commands = mock_run.call_args.args[0]
    assert [command.name for command in dispatched_commands] == ["db", "other"]


def test_lanes_auto_without_usable_partition_prints_notice_and_steps_aside(
    tmp_path: Path, capsys
) -> None:
    config = _FakeConfig(
        rootpath=tmp_path,
        invocation_args=(".", "--lanes-auto"),
        lanes_auto=True,
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands") as mock_run,
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result is None
    mock_run.assert_not_called()
    assert "--lanes-auto" in capsys.readouterr().out


def test_lanes_suggest_prints_a_reviewable_config_and_runs_nothing(
    tmp_path: Path, capsys
) -> None:
    for directory in ("db_tests", "unit_tests"):
        (tmp_path / directory).mkdir()
        (tmp_path / directory / "test_sample.py").write_text(
            "def test_ok():\n    assert True\n", encoding="utf-8"
        )
    config = _FakeConfig(
        rootpath=tmp_path, invocation_args=(".", "--lanes-suggest"), suggest=True
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands") as mock_run,
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    mock_run.assert_not_called()
    out = capsys.readouterr().out
    assert "[pytest-lanes]" in out
    assert "[pytest-lanes:db_tests]" in out


def test_lanes_explain_prints_classification_for_collected_items(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(hooks, "_lane_config", _example_lane_config())
    monkeypatch.setattr(hooks, "_rootpath", Path("C:/repo"))
    item = _FakeItem(
        path=Path("C:/repo/backend/http_adapter/tests/test_routes.py"),
        nodeid="backend/http_adapter/tests/test_routes.py::test_get",
    )
    session = SimpleNamespace(
        config=_FakeConfig(rootpath=Path("C:/repo"), explain=True), items=[item]
    )

    hooks.pytest_collection_finish(session)

    out = capsys.readouterr().out
    assert (
        "backend/http_adapter/tests/test_routes.py::test_get -> http_adapter "
        "(classifier_path_prefixes: backend/http_adapter/tests/)"
    ) in out


def test_lanes_explain_without_lane_config_raises_usage_error(monkeypatch) -> None:
    monkeypatch.setattr(hooks, "_lane_config", None)
    session = SimpleNamespace(
        config=_FakeConfig(rootpath=Path("C:/repo"), explain=True), items=[]
    )

    with pytest.raises(pytest.UsageError, match="--lanes-explain"):
        hooks.pytest_collection_finish(session)


def test_lanes_explain_skips_the_test_run_loop() -> None:
    session = SimpleNamespace(
        config=_FakeConfig(rootpath=Path("C:/repo"), explain=True)
    )

    assert hooks.pytest_runtestloop(session) is True


def test_run_loop_proceeds_normally_without_lanes_explain() -> None:
    session = SimpleNamespace(config=_FakeConfig(rootpath=Path("C:/repo")))

    assert hooks.pytest_runtestloop(session) is None
