"""Behavioral tests for ``--lanes-auto`` directory-partition lane discovery."""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.adhoc import auto_lane_config_or_none


def _write_test_file(directory: Path, name: str = "test_sample.py") -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / name).write_text("def test_ok():\n    assert True\n", encoding="utf-8")


def test_each_test_bearing_subdirectory_becomes_a_lane(tmp_path: Path) -> None:
    _write_test_file(tmp_path / "db_tests")
    _write_test_file(tmp_path / "unit_tests")
    (tmp_path / "docs").mkdir()

    config = auto_lane_config_or_none(tmp_path)

    assert config is not None
    db = config.lane_by_name("db_tests")
    assert db is not None
    assert db.classifier_path_prefixes == ("db_tests",)
    assert db.subprocess_paths == ("db_tests",)
    assert config.subprocess_order_standard == ("db_tests", "unit_tests")


def test_root_level_test_files_schedule_the_fallback_lane(tmp_path: Path) -> None:
    _write_test_file(tmp_path / "db_tests")
    _write_test_file(tmp_path / "unit_tests")
    (tmp_path / "test_stray.py").write_text(
        "def test_stray():\n    assert True\n", encoding="utf-8"
    )

    config = auto_lane_config_or_none(tmp_path)

    assert config is not None
    assert config.subprocess_order_standard == ("db_tests", "unit_tests", "other")
    fallback = config.fallback_lane()
    assert fallback is not None
    assert fallback.tolerate_no_tests is True


def test_hidden_directories_and_virtualenvs_are_never_lanes(tmp_path: Path) -> None:
    _write_test_file(tmp_path / "db_tests")
    _write_test_file(tmp_path / "unit_tests")
    _write_test_file(tmp_path / ".hidden_cache")
    _write_test_file(tmp_path / "venv" / "Lib" / "site-packages" / "pkg")
    (tmp_path / "venv" / "pyvenv.cfg").write_text("home = x\n", encoding="utf-8")

    config = auto_lane_config_or_none(tmp_path)

    assert config is not None
    lane_names = [spec.name for spec in config.lanes]
    assert ".hidden_cache" not in lane_names
    assert "venv" not in lane_names


def test_layout_without_a_usable_partition_yields_none(tmp_path: Path) -> None:
    _write_test_file(tmp_path / "only_tests")
    (tmp_path / "test_flat.py").write_text(
        "def test_flat():\n    assert True\n", encoding="utf-8"
    )

    assert auto_lane_config_or_none(tmp_path) is None


def test_directory_named_other_does_not_collide_with_the_fallback(
    tmp_path: Path,
) -> None:
    _write_test_file(tmp_path / "other")
    _write_test_file(tmp_path / "unit_tests")

    config = auto_lane_config_or_none(tmp_path)

    assert config is not None
    fallback = config.fallback_lane()
    assert fallback is not None
    assert fallback.name != "other"
