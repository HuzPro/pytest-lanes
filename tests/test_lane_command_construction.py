"""Behavioral tests for build_lane_commands driven by LaneConfig.

Mirrors the parity assertions from the pre-refactor
``test_build_lane_commands_for_full_mode`` and
``test_build_lane_commands_for_standard_mode`` so the same lane subprocesses
fire with the same argv as today, plus new coverage for the
``subprocess_ignore_other_lanes`` and ``subprocess_env_set`` features.
"""

from __future__ import annotations

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.lanes import build_lane_commands
from tests.test_lane_assignment import _example_lane_config


_FBV_NODEID = (
    "test_full_build_verification.py::"
    "test_build_produces_windows_executable"
)


def _argv_of(commands: list[dict[str, object]], lane_name: str) -> list[str]:
    for command in commands:
        if command["name"] == lane_name:
            args = command["args"]
            assert isinstance(args, list)
            return args
    raise AssertionError(f"Lane '{lane_name}' not found in commands: {[c['name'] for c in commands]}")


def test_standard_mode_emits_five_lane_subprocesses_in_canonical_order() -> None:
    config = _example_lane_config()

    commands = build_lane_commands(
        mode="standard", passthrough_args=("-q",), lane_config=config
    )

    assert [command["name"] for command in commands] == [
        "postgres",
        "timescale",
        "acceptance",
        "http_adapter",
        "other",
    ]


def test_full_mode_inserts_full_build_verification_before_http_adapter() -> None:
    config = _example_lane_config()

    commands = build_lane_commands(
        mode="full", passthrough_args=("-q",), lane_config=config
    )

    assert [command["name"] for command in commands] == [
        "postgres",
        "timescale",
        "acceptance",
        "full_build_verification",
        "http_adapter",
        "other",
    ]


def test_postgres_lane_argv_includes_subprocess_paths_and_ignores() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(mode="standard", passthrough_args=("-q",), lane_config=config)

    postgres_args = _argv_of(commands, "postgres")

    assert "backend/postgres/tests" in postgres_args
    assert "app/tests/test_config_e2e.py" in postgres_args
    assert "--ignore=backend/postgres/tests/test_sensor_logger.py" in postgres_args


def test_full_build_verification_lane_uses_nodeid_argument() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(mode="full", passthrough_args=("-q",), lane_config=config)

    fbv_args = _argv_of(commands, "full_build_verification")

    assert _FBV_NODEID in fbv_args


def test_full_build_verification_lane_carries_env_set_into_command() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(mode="full", passthrough_args=("-q",), lane_config=config)

    fbv_command = next(c for c in commands if c["name"] == "full_build_verification")

    assert ("BUILD_OUTPUT_DIR", "build/full-build-verification") in fbv_command["env_set"]


def test_other_lane_auto_ignores_paths_from_every_other_lane() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(mode="full", passthrough_args=("-q",), lane_config=config)

    other_args = _argv_of(commands, "other")

    assert "--ignore=backend/postgres/tests" in other_args
    assert "--ignore=backend/postgres/tests/test_sensor_logger.py" in other_args
    assert "--ignore=backend/http_adapter/tests" in other_args
    assert "--ignore=app/tests/test_config_e2e.py" in other_args
    assert "--ignore=experiments/keyboard-acceptance-testing/acceptance_tests" in other_args
    assert "--ignore=tests/backend_acceptance" in other_args
    assert "--ignore=test_full_build_verification.py" in other_args


def test_other_lane_also_carries_explicit_subprocess_ignore_entries() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(mode="standard", passthrough_args=("-q",), lane_config=config)

    other_args = _argv_of(commands, "other")

    assert "--ignore=experiments" in other_args


def test_passthrough_args_precede_lane_specific_args_for_every_lane() -> None:
    config = _example_lane_config()
    commands = build_lane_commands(
        mode="standard", passthrough_args=("-q", "--tb=long"), lane_config=config
    )

    for command in commands:
        args = command["args"]
        assert args[0] == "-q"
        assert args[1] == "--tb=long"


def test_empty_lane_config_with_no_subprocess_lanes_returns_empty_command_list() -> None:
    config = LaneConfig(
        lanes=(
            LaneSpec(name="marker_only", marker="unit", classifier_fallback=True),
        ),
        subprocess_order_standard=(),
        subprocess_order_full=(),
    )

    commands = build_lane_commands(mode="standard", passthrough_args=(), lane_config=config)

    assert commands == []
