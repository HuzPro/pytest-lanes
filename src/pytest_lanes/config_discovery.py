"""Rootdir lane-config discovery across the supported file formats."""

from __future__ import annotations

import configparser
from pathlib import Path

from pytest_lanes.config import LaneConfig, load_lane_config
from pytest_lanes.pyproject_config import load_lane_config_from_pyproject_or_none

DISCOVERY_ORDER = ("pytest.ini", "pyproject.toml", "tox.ini", "setup.cfg")
_PYPROJECT_FILENAME = "pyproject.toml"


def discover_lane_config(rootpath: Path) -> LaneConfig | None:
    """Return the root's lane config, or ``None`` when nothing declares one."""
    for filename in DISCOVERY_ORDER:
        config = _lane_config_in(rootpath / filename)
        if config is not None:
            return config
    return None


def _lane_config_in(candidate: Path) -> LaneConfig | None:
    if candidate.name == _PYPROJECT_FILENAME:
        return load_lane_config_from_pyproject_or_none(candidate)
    return _ini_lane_config_or_none(candidate)


def _ini_lane_config_or_none(candidate: Path) -> LaneConfig | None:
    if not candidate.exists():
        return None
    parser = configparser.ConfigParser()
    parser.read(candidate, encoding="utf-8")
    if not parser.has_section("pytest-lanes"):
        return None
    return load_lane_config(candidate)
