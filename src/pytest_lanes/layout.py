"""Where a project keeps its tests: the shared test-bearing-directory rules."""

from __future__ import annotations

import os
from fnmatch import fnmatch
from pathlib import Path

_TEST_FILE_PATTERNS = ("test_*.py", "*_test.py")
_VIRTUALENV_MARKER = "pyvenv.cfg"
_PYCACHE_DIR = "__pycache__"


def is_lane_candidate_directory(directory: Path) -> bool:
    if directory.name.startswith(".") or directory.name == _PYCACHE_DIR:
        return False
    return not (directory / _VIRTUALENV_MARKER).exists()


def is_test_filename(filename: str) -> bool:
    return any(fnmatch(filename, pattern) for pattern in _TEST_FILE_PATTERNS)


def contains_test_files(directory: Path) -> bool:
    """Whether any test file lives anywhere under ``directory``."""
    for _, _, filenames in os.walk(directory):
        if any(is_test_filename(filename) for filename in filenames):
            return True
    return False


def has_root_level_test_files(rootpath: Path) -> bool:
    """Whether test files sit directly in ``rootpath``, outside any lane."""
    return any(
        is_test_filename(entry.name) for entry in rootpath.iterdir() if entry.is_file()
    )


def test_bearing_subdirectories(rootpath: Path) -> tuple[Path, ...]:
    """The immediate subdirectories a lane could be built from, sorted by name."""
    return tuple(
        directory
        for directory in sorted(rootpath.iterdir())
        if directory.is_dir()
        and is_lane_candidate_directory(directory)
        and contains_test_files(directory)
    )
