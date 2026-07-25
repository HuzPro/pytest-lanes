"""Behavioral tests for the lane-config INI loader.

These tests describe the schema contract between ``pytest.ini`` and the
plugin. They are quality-over-quantity: each test pins one user-observable
behavior of the loader rather than exhaustively exercising every code path.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_lanes.config import (
    LaneConfigError,
    load_lane_config,
)


def _write_ini(tmp_path: Path, body: str) -> Path:
    ini_path = tmp_path / "pytest.ini"
    ini_path.write_text(body, encoding="utf-8")
    return ini_path


def test_loader_raises_when_pytest_lanes_section_is_missing(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests
""",
    )

    with pytest.raises(LaneConfigError, match="pytest-lanes"):
        load_lane_config(ini)


def test_loader_raises_when_declared_lane_has_no_section(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other
""",
    )

    with pytest.raises(LaneConfigError, match=r"\[pytest-lanes:other\]"):
        load_lane_config(ini)


def test_loader_raises_when_lane_marker_is_not_declared_in_pytest_markers(
    tmp_path: Path,
) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = bogus_marker_not_in_pytest_section
""",
    )

    with pytest.raises(LaneConfigError, match="bogus_marker_not_in_pytest_section"):
        load_lane_config(ini)


def test_loader_returns_minimal_lane_with_marker_and_paths(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
classifier_fallback = true
""",
    )

    config = load_lane_config(ini)
    other = config.lane_by_name("other")

    assert other is not None
    assert other.marker == "unit"
    assert other.classifier_fallback is True
    assert other.subprocess_paths == ()
    assert other.subprocess_ignore == ()


def test_loader_parses_lane_with_all_optional_fields(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tfull_build_verification: end-to-end build verification

[pytest-lanes]
lanes = fbv

[pytest-lanes:fbv]
marker = full_build_verification
classifier_paths = test_full_build_verification.py
subprocess_nodeids = test_full_build_verification.py::test_one
subprocess_env_set = BUILD_OUTPUT_DIR=build/full-build-verification
""",
    )

    config = load_lane_config(ini)
    fbv = config.lane_by_name("fbv")

    assert fbv is not None
    assert fbv.classifier_paths == ("test_full_build_verification.py",)
    assert fbv.subprocess_nodeids == ("test_full_build_verification.py::test_one",)
    assert fbv.subprocess_env_set == (
        ("BUILD_OUTPUT_DIR", "build/full-build-verification"),
    )


def test_loader_preserves_lane_declaration_order(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests
\tpostgres_integration: pg tests
\ttimescale_integration: ts tests

[pytest-lanes]
lanes = timescale postgres other
subprocess_order_standard = postgres timescale other

[pytest-lanes:timescale]
marker = timescale_integration

[pytest-lanes:postgres]
marker = postgres_integration

[pytest-lanes:other]
marker = unit
classifier_fallback = true
""",
    )

    config = load_lane_config(ini)

    assert [spec.name for spec in config.lanes] == ["timescale", "postgres", "other"]
    assert [spec.name for spec in config.standard_subprocess_lanes()] == [
        "postgres",
        "timescale",
        "other",
    ]


def test_loader_raises_when_two_lanes_set_ignore_other_lanes(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = first second

[pytest-lanes:first]
marker = unit
subprocess_ignore_other_lanes = true

[pytest-lanes:second]
marker = unit
subprocess_ignore_other_lanes = true
""",
    )

    with pytest.raises(LaneConfigError, match="ignore_other_lanes"):
        load_lane_config(ini)


def test_loader_raises_when_subprocess_order_references_unknown_lane(
    tmp_path: Path,
) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other
subprocess_order_standard = other ghost_lane

[pytest-lanes:other]
marker = unit
""",
    )

    with pytest.raises(LaneConfigError, match="ghost_lane"):
        load_lane_config(ini)


def test_loader_distinguishes_standard_and_full_subprocess_orderings(
    tmp_path: Path,
) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests
\tfull_build_verification: fbv

[pytest-lanes]
lanes = postgres fbv other
subprocess_order_standard = postgres other
subprocess_order_full = postgres fbv other

[pytest-lanes:postgres]
marker = unit

[pytest-lanes:fbv]
marker = full_build_verification

[pytest-lanes:other]
marker = unit
""",
    )

    config = load_lane_config(ini)

    assert [spec.name for spec in config.standard_subprocess_lanes()] == [
        "postgres",
        "other",
    ]
    assert [spec.name for spec in config.full_subprocess_lanes()] == [
        "postgres",
        "fbv",
        "other",
    ]


def test_loader_parses_max_workers_from_the_index_section(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other
max_workers = 3

[pytest-lanes:other]
marker = unit
""",
    )

    config = load_lane_config(ini)

    assert config.max_workers == 3


def test_loader_leaves_max_workers_unset_when_absent(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
""",
    )

    config = load_lane_config(ini)

    assert config.max_workers is None


def test_loader_parses_lane_numprocesses_for_in_lane_xdist(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
lane_numprocesses = 4
""",
    )

    config = load_lane_config(ini)

    lane = config.lane_by_name("other")
    assert lane is not None
    assert lane.lane_numprocesses == 4


def test_loader_rejects_non_positive_lane_numprocesses(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
lane_numprocesses = 0
""",
    )

    with pytest.raises(LaneConfigError, match="lane_numprocesses"):
        load_lane_config(ini)


def test_loader_parses_divisible_files_and_shard_min_saving(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other
shard_min_saving = 8.5

[pytest-lanes:other]
marker = unit
divisible = files
""",
    )

    config = load_lane_config(ini)

    lane = config.lane_by_name("other")
    assert lane is not None
    assert lane.divisible is True
    assert config.shard_min_saving == 8.5


def test_loader_defaults_shard_min_saving_and_divisible_off(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
""",
    )

    config = load_lane_config(ini)

    lane = config.lane_by_name("other")
    assert lane is not None
    assert lane.divisible is False
    assert config.shard_min_saving == 5.0


def test_loader_rejects_divisible_values_other_than_files(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
divisible = tests
""",
    )

    with pytest.raises(LaneConfigError, match="divisible"):
        load_lane_config(ini)


def test_loader_parses_tolerate_no_tests_for_fallback_lanes(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other

[pytest-lanes:other]
marker = unit
classifier_fallback = true
tolerate_no_tests = true
""",
    )

    config = load_lane_config(ini)

    lane = config.lane_by_name("other")
    assert lane is not None
    assert lane.tolerate_no_tests is True


def test_loader_raises_when_max_workers_is_not_an_integer(tmp_path: Path) -> None:
    ini = _write_ini(
        tmp_path,
        """
[pytest]
markers =
\tunit: unit tests

[pytest-lanes]
lanes = other
max_workers = plenty

[pytest-lanes:other]
marker = unit
""",
    )

    with pytest.raises(LaneConfigError, match="max_workers"):
        load_lane_config(ini)
