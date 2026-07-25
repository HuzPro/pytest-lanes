"""Behavioral tests for the lane-config ``pyproject.toml`` loader.

These tests describe the schema contract between ``[tool.pytest-lanes]`` and
the plugin. They mirror the INI loader's contract — same dataclasses, same
error voice — and additionally pin the strictness that real TOML types make
possible: wrong types and unknown keys are refused rather than ignored.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from pytest_lanes.config import LaneConfigError
from pytest_lanes.pyproject_config import (
    load_lane_config_from_pyproject,
    load_lane_config_from_pyproject_or_none,
)


def _write_pyproject(tmp_path: Path, body: str) -> Path:
    pyproject_path = tmp_path / "pyproject.toml"
    pyproject_path.write_text(body, encoding="utf-8")
    return pyproject_path


def test_loader_raises_when_tool_pytest_lanes_table_is_missing(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]
""",
    )

    with pytest.raises(LaneConfigError, match=r"tool\.pytest-lanes"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_returns_minimal_lane_with_marker_and_no_optional_fields(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_fallback = true
""",
    )

    config = load_lane_config_from_pyproject(pyproject)
    other = config.lane_by_name("other")

    assert other is not None
    assert other.marker == "unit"
    assert other.classifier_fallback is True
    assert other.subprocess_paths == ()
    assert other.subprocess_ignore == ()


def test_loader_raises_when_lanes_array_is_empty(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = []
""",
    )

    with pytest.raises(LaneConfigError, match="at least one lane"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_declared_lane_has_no_lane_table(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
""",
    )

    with pytest.raises(LaneConfigError, match=r"\[tool\.pytest-lanes\.lane\.other\]"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_lane_marker_is_not_declared_in_ini_options_markers(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "bogus_marker_not_in_ini_options"
""",
    )

    with pytest.raises(LaneConfigError, match="bogus_marker_not_in_ini_options"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_accepts_markers_declared_as_one_newline_separated_string(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        '''
[tool.pytest.ini_options]
markers = """
unit: unit tests
postgres_integration: pg tests
"""

[tool.pytest-lanes]
lanes = ["postgres"]

[tool.pytest-lanes.lane.postgres]
marker = "postgres_integration"
''',
    )

    config = load_lane_config_from_pyproject(pyproject)
    postgres = config.lane_by_name("postgres")

    assert postgres is not None
    assert postgres.marker == "postgres_integration"


def test_loader_preserves_lane_declaration_order(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests", "postgres_integration: pg", "timescale_integration: ts"]

[tool.pytest-lanes]
lanes = ["timescale", "postgres", "other"]
subprocess_order_standard = ["postgres", "timescale", "other"]

[tool.pytest-lanes.lane.timescale]
marker = "timescale_integration"

[tool.pytest-lanes.lane.postgres]
marker = "postgres_integration"

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_fallback = true
""",
    )

    config = load_lane_config_from_pyproject(pyproject)

    assert [spec.name for spec in config.lanes] == ["timescale", "postgres", "other"]
    assert [spec.name for spec in config.standard_subprocess_lanes()] == [
        "postgres",
        "timescale",
        "other",
    ]


def test_loader_distinguishes_standard_and_full_subprocess_orderings(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests", "full_build_verification: fbv"]

[tool.pytest-lanes]
lanes = ["postgres", "fbv", "other"]
subprocess_order_standard = ["postgres", "other"]
subprocess_order_full = ["postgres", "fbv", "other"]

[tool.pytest-lanes.lane.postgres]
marker = "unit"

[tool.pytest-lanes.lane.fbv]
marker = "full_build_verification"

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    config = load_lane_config_from_pyproject(pyproject)

    assert [spec.name for spec in config.standard_subprocess_lanes()] == [
        "postgres",
        "other",
    ]
    assert [spec.name for spec in config.full_subprocess_lanes()] == [
        "postgres",
        "fbv",
        "other",
    ]


def test_loader_raises_when_subprocess_order_references_unknown_lane(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
subprocess_order_standard = ["other", "ghost_lane"]

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    with pytest.raises(LaneConfigError, match="ghost_lane"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_two_lanes_set_ignore_other_lanes(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["first", "second"]

[tool.pytest-lanes.lane.first]
marker = "unit"
subprocess_ignore_other_lanes = true

[tool.pytest-lanes.lane.second]
marker = "unit"
subprocess_ignore_other_lanes = true
""",
    )

    with pytest.raises(LaneConfigError, match="ignore_other_lanes"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_parses_max_workers_from_the_index_table(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
max_workers = 3

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    config = load_lane_config_from_pyproject(pyproject)

    assert config.max_workers == 3


def test_loader_raises_when_max_workers_is_a_float(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
max_workers = 3.0

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    with pytest.raises(LaneConfigError, match="max_workers"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_accepts_an_integer_shard_min_saving(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
shard_min_saving = 8

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    config = load_lane_config_from_pyproject(pyproject)

    assert config.shard_min_saving == 8.0


def test_loader_defaults_shard_min_saving_and_max_workers_when_absent(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    config = load_lane_config_from_pyproject(pyproject)

    assert config.shard_min_saving == 5.0
    assert config.max_workers is None


def test_loader_parses_divisible_files_and_lane_numprocesses(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
divisible = "files"
lane_numprocesses = 4
""",
    )

    config = load_lane_config_from_pyproject(pyproject)
    lane = config.lane_by_name("other")

    assert lane is not None
    assert lane.divisible is True
    assert lane.lane_numprocesses == 4


def test_loader_rejects_divisible_values_other_than_files(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
divisible = "tests"
""",
    )

    with pytest.raises(LaneConfigError, match="mutually independent"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_rejects_lane_numprocesses_of_zero(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
lane_numprocesses = 0
""",
    )

    with pytest.raises(LaneConfigError, match="lane_numprocesses must be positive"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_rejects_a_float_lane_numprocesses(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
lane_numprocesses = 4.0
""",
    )

    with pytest.raises(LaneConfigError, match="lane_numprocesses must be an integer"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_parses_lane_with_every_optional_field(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["full_build_verification: end-to-end build verification"]

[tool.pytest-lanes]
lanes = ["fbv"]

[tool.pytest-lanes.lane.fbv]
marker = "full_build_verification"
classifier_paths = ["tests/test_full_build_verification.py"]
classifier_path_prefixes = ["tests/integration/"]
classifier_path_suffix = "_pg.py"
classifier_class_base_names = ["PostgresTestCase"]
classifier_fallback = false
subprocess_paths = ["tests/integration"]
subprocess_nodeids = ["tests/test_full_build_verification.py::test_one"]
subprocess_ignore = ["tests/integration/slow"]
subprocess_ignore_other_lanes = true
tolerate_no_tests = true
lane_numprocesses = 2
divisible = "files"

[tool.pytest-lanes.lane.fbv.subprocess_env_set]
BUILD_OUTPUT_DIR = "build/full-build-verification"
PYTHONUTF8 = "1"
""",
    )

    config = load_lane_config_from_pyproject(pyproject)
    fbv = config.lane_by_name("fbv")

    assert fbv is not None
    assert fbv.classifier_paths == ("tests/test_full_build_verification.py",)
    assert fbv.classifier_path_prefixes == ("tests/integration/",)
    assert fbv.classifier_path_suffix == "_pg.py"
    assert fbv.classifier_class_base_names == ("PostgresTestCase",)
    assert fbv.classifier_fallback is False
    assert fbv.subprocess_paths == ("tests/integration",)
    assert fbv.subprocess_nodeids == (
        "tests/test_full_build_verification.py::test_one",
    )
    assert fbv.subprocess_ignore == ("tests/integration/slow",)
    assert fbv.subprocess_ignore_other_lanes is True
    assert fbv.tolerate_no_tests is True
    assert fbv.lane_numprocesses == 2
    assert fbv.divisible is True


def test_loader_preserves_subprocess_env_set_declaration_order(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
subprocess_env_set = { ZEBRA = "last", ALPHA = "first" }
""",
    )

    config = load_lane_config_from_pyproject(pyproject)
    lane = config.lane_by_name("other")

    assert lane is not None
    assert lane.subprocess_env_set == (("ZEBRA", "last"), ("ALPHA", "first"))


def test_loader_raises_when_an_array_field_contains_a_non_string(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_paths = ["tests/test_one.py", 7]
""",
    )

    with pytest.raises(LaneConfigError, match="classifier_paths"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_lanes_is_a_string_instead_of_an_array(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = "other"

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    with pytest.raises(LaneConfigError, match="lanes must be an array of strings"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_subprocess_env_set_value_is_not_a_string(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
subprocess_env_set = { WORKERS = 4 }
""",
    )

    with pytest.raises(LaneConfigError, match="subprocess_env_set"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_a_lane_table_omits_the_marker(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
classifier_fallback = true
""",
    )

    with pytest.raises(LaneConfigError, match="missing the required 'marker' field"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_raises_when_marker_is_not_a_string(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = 7
""",
    )

    with pytest.raises(LaneConfigError, match="marker must be a string"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_rejects_an_unknown_key_in_the_index_table(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
max_worker = 3

[tool.pytest-lanes.lane.other]
marker = "unit"
""",
    )

    with pytest.raises(LaneConfigError, match="max_worker.*max_workers"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_rejects_an_unknown_key_in_a_lane_table(tmp_path: Path) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_path = ["tests/test_one.py"]
""",
    )

    with pytest.raises(LaneConfigError, match="classifier_path.*classifier_paths"):
        load_lane_config_from_pyproject(pyproject)


def test_loader_rejects_a_lane_table_for_a_lane_that_is_not_declared(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"

[tool.pytest-lanes.lane.ghost]
marker = "unit"
""",
    )

    with pytest.raises(LaneConfigError, match="ghost"):
        load_lane_config_from_pyproject(pyproject)


def test_dormant_loader_returns_none_when_the_pyproject_does_not_exist(
    tmp_path: Path,
) -> None:
    assert load_lane_config_from_pyproject_or_none(tmp_path / "pyproject.toml") is None


def test_dormant_loader_returns_none_when_the_pyproject_declares_no_lanes_table(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[project]
name = "unrelated-project"

[tool.pytest.ini_options]
markers = ["unit: unit tests"]
""",
    )

    assert load_lane_config_from_pyproject_or_none(pyproject) is None


def test_dormant_loader_loads_the_config_when_the_lanes_table_exists(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]

[tool.pytest-lanes.lane.other]
marker = "unit"
classifier_fallback = true
""",
    )

    config = load_lane_config_from_pyproject_or_none(pyproject)

    assert config is not None
    assert config.lane_by_name("other") is not None


def test_dormant_loader_still_raises_when_the_lanes_table_is_malformed(
    tmp_path: Path,
) -> None:
    pyproject = _write_pyproject(
        tmp_path,
        """
[tool.pytest.ini_options]
markers = ["unit: unit tests"]

[tool.pytest-lanes]
lanes = ["other"]
""",
    )

    with pytest.raises(LaneConfigError, match=r"\[tool\.pytest-lanes\.lane\.other\]"):
        load_lane_config_from_pyproject_or_none(pyproject)


def test_loader_reports_unparsable_toml_as_a_lane_config_error(tmp_path: Path) -> None:
    pyproject = _write_pyproject(tmp_path, "[tool.pytest-lanes\nlanes = ['other']\n")

    with pytest.raises(LaneConfigError, match="pyproject.toml"):
        load_lane_config_from_pyproject(pyproject)
