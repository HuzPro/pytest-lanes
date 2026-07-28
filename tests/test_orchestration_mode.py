"""Behavioral tests for ``orchestration_mode``."""

from __future__ import annotations

import os
from unittest.mock import patch

from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV
from pytest_lanes.mode import orchestration_mode


class _FakeConfig:
    def __init__(
        self,
        full: bool = False,
        explain: bool = False,
        invocation_args: tuple[str, ...] = (),
    ) -> None:
        self._full = full
        self._explain = explain
        self.invocation_params = type("InvocationParams", (), {"args": invocation_args})

    def getoption(self, option_name: str) -> object:
        if option_name == "--lanes-full":
            return self._full
        if option_name == "--lanes-explain":
            return self._explain
        return False


def _without_child_env_var():
    return patch.dict(os.environ, {TEST_ORCHESTRATION_CHILD_ENV: ""}, clear=False)


def test_full_flag_with_dot_target_yields_full_mode() -> None:
    config = _FakeConfig(full=True, invocation_args=(".", "--lanes-full"))

    with _without_child_env_var():
        assert orchestration_mode(config) == "full"


def test_dot_target_without_full_flag_yields_standard_mode() -> None:
    config = _FakeConfig(invocation_args=(".",))

    with _without_child_env_var():
        assert orchestration_mode(config) == "standard"


def test_targeted_path_bypasses_orchestration_even_with_full_flag() -> None:
    config = _FakeConfig(
        full=True, invocation_args=("test_full_build_verification.py", "--lanes-full")
    )

    assert orchestration_mode(config) is None


def test_keyword_filter_bypasses_orchestration() -> None:
    config = _FakeConfig(
        full=True, invocation_args=(".", "-k", "checkout", "--lanes-full")
    )

    assert orchestration_mode(config) is None


def test_lane_flag_bypasses_orchestration() -> None:
    config = _FakeConfig(invocation_args=(".", "--lane=postgres"))

    with _without_child_env_var():
        assert orchestration_mode(config) is None


def test_lanes_explain_flag_bypasses_orchestration() -> None:
    config = _FakeConfig(explain=True, invocation_args=(".", "--lanes-explain"))

    with _without_child_env_var():
        assert orchestration_mode(config) is None


def test_child_environment_variable_disables_orchestration() -> None:
    config = _FakeConfig(invocation_args=(".",))

    with patch.dict(os.environ, {TEST_ORCHESTRATION_CHILD_ENV: "1"}, clear=False):
        assert orchestration_mode(config) is None
