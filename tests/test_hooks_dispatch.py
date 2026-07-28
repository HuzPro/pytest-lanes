"""Integration-style tests for the orchestration dispatch path."""

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
        no_shard: bool = False,
        show_output: bool = False,
    ) -> None:
        self.rootpath = rootpath
        self._full = full
        self._lane = lane
        self._max_workers = max_workers
        self._explain = explain
        self._lane_defs = lane_defs
        self._lanes_auto = lanes_auto
        self._suggest = suggest
        self._no_shard = no_shard
        self._show_output = show_output
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
        if option_name == "--lanes-no-shard":
            return self._no_shard
        if option_name == "--lanes-show-output":
            return self._show_output
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


def test_disabling_capture_streams_lane_output_live() -> None:
    # Given `pytest . -s`: stream children instead of folding output.
    config = _FakeConfig(rootpath=Path("C:/repo"), invocation_args=(".", "-s"))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["show_lane_output"] is True


def test_explicit_show_output_flag_streams_lane_output_live() -> None:
    # Given the flag, live streaming happens even though capture is on.
    config = _FakeConfig(
        rootpath=Path("C:/repo"), invocation_args=(".",), show_output=True
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["show_lane_output"] is True


def test_ordinary_run_keeps_lane_output_folded_into_the_summary() -> None:
    config = _FakeConfig(rootpath=Path("C:/repo"), invocation_args=(".", "-q"))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(
            hooks, "_load_lane_config_for", return_value=_example_lane_config()
        ),
    ):
        hooks.pytest_cmdline_main(config)

    assert mock_run.call_args.kwargs["show_lane_output"] is False


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
        "redis",
        "acceptance",
        "api",
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
        "redis",
        "acceptance",
        "full_build_verification",
        "api",
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


def test_lane_numprocesses_without_xdist_installed_is_a_usage_error(
    tmp_path: Path,
) -> None:
    from pytest_lanes.config import LaneConfig, LaneSpec

    lane_config = LaneConfig(
        lanes=(
            LaneSpec(
                name="units",
                marker="unit",
                subprocess_paths=("u",),
                lane_numprocesses=2,
            ),
        ),
        subprocess_order_standard=("units",),
    )
    config = _FakeConfig(rootpath=tmp_path, invocation_args=(".",))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands") as mock_run,
        patch.object(hooks, "_load_lane_config_for", return_value=lane_config),
        patch.object(hooks, "_xdist_is_available", return_value=False),
        pytest.raises(pytest.UsageError, match="pytest-xdist"),
    ):
        hooks.pytest_cmdline_main(config)

    mock_run.assert_not_called()


def test_xdist_worker_processes_never_start_their_own_recorder(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(hooks, "_child_recorder", None)
    monkeypatch.setenv("PYTEST_LANES_DURATIONS_OUT", str(tmp_path / "out.json"))
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw0")

    hooks.pytest_sessionstart(SimpleNamespace(config=None))

    assert hooks._child_recorder is None


def test_lanes_suggest_prefers_balanced_partition_when_recorded_data_exists(
    tmp_path: Path, capsys
) -> None:
    from pytest_lanes.durations import LaneRecord, duration_store_for_rootdir

    duration_store_for_rootdir(tmp_path).record(
        {
            "db_tests": LaneRecord(
                total=30.0,
                startup=2.0,
                collect=1.0,
                files=(("db_tests/test_a.py", 14.0), ("db_tests/test_b.py", 13.0)),
            ),
            "unit_tests": LaneRecord(
                total=6.0,
                files=(("unit_tests/test_u.py", 5.0),),
            ),
        }
    )
    config = _FakeConfig(
        rootpath=tmp_path, invocation_args=(".", "--lanes-suggest"), suggest=True
    )

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands"),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    out = capsys.readouterr().out
    assert "balanced suggestion" in out
    assert "[pytest-lanes:rest]" in out
    assert "projected:" in out
    assert "# pytest-lanes suggestion - generated" not in out


def test_lanes_suggest_without_recorded_data_prints_static_scan_and_tip(
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
        patch.object(hooks, "run_lane_commands"),
    ):
        hooks.pytest_cmdline_main(config)

    out = capsys.readouterr().out
    assert "# pytest-lanes suggestion - generated" in out
    assert "duration-balanced" in out


def _seeded_divisible_project(tmp_path: Path):
    """A rootpath with a divisible lane, recorded data, and real files."""
    from pytest_lanes.config import LaneConfig, LaneSpec
    from pytest_lanes.durations import LaneRecord, duration_store_for_rootdir

    db_dir = tmp_path / "db"
    db_dir.mkdir()
    for name in ("test_a.py", "test_b.py", "test_c.py", "test_d.py"):
        (db_dir / name).write_text("def test_ok():\n    assert True\n", "utf-8")

    lane_config = LaneConfig(
        lanes=(
            LaneSpec(
                name="postgres",
                marker="postgres_integration",
                classifier_path_prefixes=("db/",),
                subprocess_paths=("db",),
                divisible=True,
            ),
            LaneSpec(
                name="other",
                marker="unit",
                classifier_fallback=True,
                subprocess_ignore_other_lanes=True,
                tolerate_no_tests=True,
            ),
        ),
        subprocess_order_standard=("postgres", "other"),
    )
    duration_store_for_rootdir(tmp_path).record(
        {
            "postgres": LaneRecord(
                total=30.0,
                startup=2.0,
                collect=1.0,
                files=(
                    ("db/test_a.py", 7.0),
                    ("db/test_b.py", 7.0),
                    ("db/test_c.py", 7.0),
                    ("db/test_d.py", 6.0),
                ),
            ),
            "other": LaneRecord(total=4.0),
        }
    )
    return lane_config


def test_divisible_lane_with_recorded_data_dispatches_shards(
    tmp_path: Path, capsys
) -> None:
    lane_config = _seeded_divisible_project(tmp_path)
    config = _FakeConfig(rootpath=tmp_path, invocation_args=(".",))

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(hooks, "_load_lane_config_for", return_value=lane_config),
        patch.object(hooks, "detected_cpu_count", return_value=4),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result == 0
    dispatched = mock_run.call_args.args[0]
    assert [command.name for command in dispatched] == [
        "postgres~1of2",
        "postgres~2of2",
        "other",
    ]
    assert mock_run.call_args.kwargs["shard_parents"] == {
        "postgres~1of2": "postgres",
        "postgres~2of2": "postgres",
    }
    assert "postgres~1of2" in mock_run.call_args.kwargs["reproduce_overrides"]
    assert "sharded postgres into 2" in capsys.readouterr().out
    assert (
        tmp_path / ".pytest_cache" / "v" / "pytest-lanes" / "shard_plan.json"
    ).exists()


def test_lanes_no_shard_flag_disables_planning(tmp_path: Path) -> None:
    lane_config = _seeded_divisible_project(tmp_path)
    config = _FakeConfig(rootpath=tmp_path, invocation_args=(".",), no_shard=True)

    with (
        _without_child_env_var(),
        patch.object(hooks, "run_lane_commands", return_value=0) as mock_run,
        patch.object(hooks, "_load_lane_config_for", return_value=lane_config),
        patch.object(hooks, "detected_cpu_count", return_value=4),
    ):
        hooks.pytest_cmdline_main(config)

    dispatched = mock_run.call_args.args[0]
    assert [command.name for command in dispatched] == ["postgres", "other"]


def test_lanes_explain_prints_classification_for_collected_items(
    capsys, monkeypatch
) -> None:
    monkeypatch.setattr(hooks, "_lane_config", _example_lane_config())
    monkeypatch.setattr(hooks, "_rootpath", Path("C:/repo"))
    item = _FakeItem(
        path=Path("C:/repo/services/api/tests/test_routes.py"),
        nodeid="services/api/tests/test_routes.py::test_get",
    )
    session = SimpleNamespace(
        config=_FakeConfig(rootpath=Path("C:/repo"), explain=True), items=[item]
    )

    hooks.pytest_collection_finish(session)

    out = capsys.readouterr().out
    assert (
        "services/api/tests/test_routes.py::test_get -> api "
        "(classifier_path_prefixes: services/api/tests/)"
    ) in out


def test_lanes_explain_footer_shows_divisibility_and_persisted_plan(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    from pytest_lanes.sharding import persist_first_shard, shard_plan_path_for_rootdir

    lane_config = _seeded_divisible_project(tmp_path)
    persist_first_shard(
        shard_plan_path_for_rootdir(tmp_path),
        "postgres",
        ("db/test_a.py", "db/test_b.py"),
    )
    monkeypatch.setattr(hooks, "_lane_config", lane_config)
    monkeypatch.setattr(hooks, "_rootpath", tmp_path)
    session = SimpleNamespace(
        config=_FakeConfig(rootpath=tmp_path, explain=True), items=[]
    )

    hooks.pytest_collection_finish(session)

    out = capsys.readouterr().out
    assert "Divisible lanes: postgres" in out
    assert "Persisted shard plan: postgres" in out
    assert "db/test_a.py" in out


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
