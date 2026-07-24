"""Behavioral tests: path- and class-based lane assignment driven by LaneConfig.

The example config below models a realistic project with container-backed
lanes (postgres, timescale), a build-verification lane, and a fallback
``other`` lane. Each test pins one classification rule a user relies on;
changing an assertion here means a test file would silently shift into a
different lane subprocess.
"""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.lanes import lane_for_item


class _FakeItem:
    def __init__(
        self,
        path: Path,
        nodeid: str,
        test_class: type | None = None,
    ) -> None:
        self.path = path
        self.nodeid = nodeid
        self.cls = test_class


def _example_lane_config() -> LaneConfig:
    """Build a LaneConfig for a realistic multi-lane project layout.

    Exercises every classifier kind: exact paths, path prefixes, class base
    names, a fallback lane, and both subprocess order lists.
    """
    return LaneConfig(
        lanes=(
            LaneSpec(
                name="full_build_verification",
                marker="full_build_verification",
                classifier_paths=("test_full_build_verification.py",),
                subprocess_nodeids=(
                    (
                        "test_full_build_verification.py::"
                        "test_build_produces_windows_executable"
                    ),
                ),
                subprocess_env_set=(
                    ("BUILD_OUTPUT_DIR", "build/full-build-verification"),
                ),
            ),
            LaneSpec(
                name="timescale",
                marker="timescale_integration",
                classifier_paths=("backend/postgres/tests/test_sensor_logger.py",),
                subprocess_paths=("backend/postgres/tests/test_sensor_logger.py",),
            ),
            LaneSpec(
                name="postgres",
                marker="postgres_integration",
                classifier_path_prefixes=("backend/postgres/tests/",),
                classifier_paths=("app/tests/test_first_run_configuration_service.py",),
                classifier_class_base_names=(
                    "PostgresTestCase",
                    "SharedPostgresContainerTestCase",
                    "TimescaleTestCase",
                ),
                subprocess_paths=(
                    "backend/postgres/tests",
                    "app/tests/test_tracker_e2e.py",
                    "app/tests/test_config_e2e.py",
                    "app/tests/test_database_schema_ensurer.py",
                    "app/tests/test_first_run_configuration_service.py",
                ),
                subprocess_ignore=("backend/postgres/tests/test_sensor_logger.py",),
            ),
            LaneSpec(
                name="http_adapter",
                marker="unit",
                classifier_path_prefixes=("backend/http_adapter/tests/",),
                subprocess_paths=("backend/http_adapter/tests",),
            ),
            LaneSpec(
                name="e2e",
                marker="e2e",
                classifier_paths=(
                    "app/tests/test_tracker_e2e.py",
                    "app/tests/test_config_e2e.py",
                    "app/tests/test_database_schema_ensurer.py",
                ),
            ),
            LaneSpec(
                name="acceptance",
                marker="acceptance",
                classifier_path_prefixes=(
                    "experiments/keyboard-acceptance-testing/acceptance_tests",
                    "tests/backend_acceptance",
                ),
                subprocess_paths=(
                    "experiments/keyboard-acceptance-testing/acceptance_tests",
                    "tests/backend_acceptance",
                ),
            ),
            LaneSpec(
                name="other",
                marker="unit",
                classifier_fallback=True,
                subprocess_ignore_other_lanes=True,
                subprocess_ignore=(
                    "experiments",
                    "test_full_build_verification.py",
                ),
            ),
        ),
        subprocess_order_standard=(
            "postgres",
            "timescale",
            "acceptance",
            "http_adapter",
            "other",
        ),
        subprocess_order_full=(
            "postgres",
            "timescale",
            "acceptance",
            "full_build_verification",
            "http_adapter",
            "other",
        ),
    )


_ROOT = Path("C:/repo")
_CONFIG = _example_lane_config()


def test_postgres_tests_are_classified_as_postgres_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "postgres" / "tests" / "test_activity_logger.py",
        nodeid=(
            "backend/postgres/tests/test_activity_logger.py::"
            "TestActivityLoggerRepository::test_create_activity"
        ),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "postgres_integration"


def test_timescale_sensor_logger_is_classified_as_timescale_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "postgres" / "tests" / "test_sensor_logger.py",
        nodeid="backend/postgres/tests/test_sensor_logger.py::test_one",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "timescale_integration"


def test_fastapi_tests_are_classified_with_unit_marker() -> None:
    item = _FakeItem(
        path=_ROOT / "backend" / "http_adapter" / "tests" / "test_activity_logger.py",
        nodeid="backend/http_adapter/tests/test_activity_logger.py::test_one",
    )

    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "http_adapter"
    assert spec.marker == "unit"


def test_activity_logger_e2e_paths_are_classified_as_e2e_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_config_e2e.py",
        nodeid="app/tests/test_config_e2e.py::test_round_trip",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "e2e"


def test_unmatched_tests_fall_back_to_unit_marker_via_other_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_activity_tracker_logic.py",
        nodeid="app/tests/test_activity_tracker_logic.py::test_one",
    )

    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "other"
    assert spec.marker == "unit"


def test_full_build_verification_filename_is_classified_as_fbv_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "test_full_build_verification.py",
        nodeid=(
            "test_full_build_verification.py::test_build_produces_windows_executable"
        ),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "full_build_verification"


def test_acceptance_path_prefix_is_classified_as_acceptance_lane() -> None:
    item = _FakeItem(
        path=_ROOT
        / "tests"
        / "backend_acceptance"
        / "instrastructure"
        / "test_time_point_system.py",
        nodeid="tests/backend_acceptance/instrastructure/test_time_point_system.py::test_one",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "acceptance"


def test_first_run_configuration_service_is_classified_as_postgres_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_first_run_configuration_service.py",
        nodeid=(
            "app/tests/test_first_run_configuration_service.py::"
            "TestFirstRunConfigurationServiceIntegration::"
            "test_save_should_bootstrap_app_config_and_persist_settings_on_fresh_database"
        ),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "postgres_integration"


def test_class_base_name_promotes_unit_test_into_postgres_lane() -> None:
    postgres_base = type("PostgresTestCase", (), {})
    fake_postgres_test_class = type("TestContainerBacked", (postgres_base,), {})
    item = _FakeItem(
        path=_ROOT / "backend" / "http_adapter" / "tests" / "test_activity_logger.py",
        nodeid="backend/http_adapter/tests/test_activity_logger.py::test_one",
        test_class=fake_postgres_test_class,
    )

    # A test whose class inherits from a container-base type belongs to the
    # postgres lane regardless of its file path.
    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "postgres"
