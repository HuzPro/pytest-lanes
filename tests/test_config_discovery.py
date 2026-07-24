"""Behavioral tests for config discovery and dormant-mode behavior.

These behaviors are what make the plugin safe to install globally: it must
stay dormant in projects without a ``[pytest-lanes]`` section, discover its
section in any of pytest.ini / tox.ini / setup.cfg, and fall back to a plain
pytest run when lanes exist but no subprocess order is declared.
"""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

from pytest_lanes import hooks
from pytest_lanes.config import LaneConfig, LaneSpec, load_lane_config_or_none
from pytest_lanes.constants import TEST_ORCHESTRATION_CHILD_ENV

_MINIMAL_LANES_BODY = """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
classifier_fallback = true
"""

_SETUP_CFG_BODY = """
[tool:pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
classifier_fallback = true
"""


def test_discovery_returns_none_when_no_config_file_declares_lanes(
    tmp_path: Path,
) -> None:
    (tmp_path / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")

    assert load_lane_config_or_none(tmp_path) is None


def test_discovery_returns_none_when_rootdir_has_no_ini_files(tmp_path: Path) -> None:
    assert load_lane_config_or_none(tmp_path) is None


def test_discovery_finds_lanes_section_in_tox_ini(tmp_path: Path) -> None:
    (tmp_path / "tox.ini").write_text(_MINIMAL_LANES_BODY, encoding="utf-8")

    config = load_lane_config_or_none(tmp_path)

    assert config is not None
    assert config.lane_by_name("other") is not None


def test_discovery_reads_markers_from_tool_pytest_section_in_setup_cfg(
    tmp_path: Path,
) -> None:
    (tmp_path / "setup.cfg").write_text(_SETUP_CFG_BODY, encoding="utf-8")

    config = load_lane_config_or_none(tmp_path)

    assert config is not None
    other = config.lane_by_name("other")
    assert other is not None
    assert other.marker == "unit"


def test_discovery_prefers_pytest_ini_over_tox_ini(tmp_path: Path) -> None:
    (tmp_path / "pytest.ini").write_text(_MINIMAL_LANES_BODY, encoding="utf-8")
    (tmp_path / "tox.ini").write_text(
        _MINIMAL_LANES_BODY.replace("other", "toxlane"), encoding="utf-8"
    )

    config = load_lane_config_or_none(tmp_path)

    assert config is not None
    assert config.lane_by_name("other") is not None


class _FakeConfig:
    def __init__(
        self, rootpath: Path, invocation_args: tuple[str, ...] = (".",)
    ) -> None:
        self.rootpath = rootpath
        self.invocation_params = type("InvocationParams", (), {"args": invocation_args})

    def getoption(self, option_name: str, default: object = None) -> object:
        if option_name == "--lanes-full":
            return False
        return default


def test_cmdline_main_returns_none_when_lanes_declare_no_subprocess_order() -> None:
    marker_only_config = LaneConfig(
        lanes=(LaneSpec(name="other", marker="unit", classifier_fallback=True),),
    )
    config = _FakeConfig(rootpath=Path("C:/repo"))

    with (
        patch.dict(os.environ, {TEST_ORCHESTRATION_CHILD_ENV: ""}, clear=False),
        patch.object(hooks, "run_lane_commands") as mock_run,
        patch.object(hooks, "_load_lane_config_for", return_value=marker_only_config),
    ):
        result = hooks.pytest_cmdline_main(config)

    assert result is None
    mock_run.assert_not_called()
