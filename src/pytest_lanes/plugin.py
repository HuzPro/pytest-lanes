"""``pytest11`` entry-point module.

Re-exports the hook callables so pytest discovers them when the package is
installed. Vendored setups can import the same names from a repo-root
``conftest.py`` instead of installing the package — see README.md.
"""

from pytest_lanes.hooks import (
    pytest_addoption,
    pytest_cmdline_main,
    pytest_collection_finish,
    pytest_collection_modifyitems,
    pytest_configure,
    pytest_runtest_setup,
    pytest_runtest_teardown,
    pytest_runtestloop,
)

__all__ = [
    "pytest_addoption",
    "pytest_cmdline_main",
    "pytest_collection_finish",
    "pytest_collection_modifyitems",
    "pytest_configure",
    "pytest_runtest_setup",
    "pytest_runtest_teardown",
    "pytest_runtestloop",
]
