"""Behavioral tests: path- and class-based lane assignment driven by LaneConfig."""

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
    """Build a LaneConfig for a realistic multi-lane project layout."""
    return LaneConfig(
        lanes=(
            LaneSpec(
                name="full_build_verification",
                marker="full_build_verification",
                classifier_paths=("test_full_build_verification.py",),
                subprocess_nodeids=(
                    ("test_full_build_verification.py::test_build_produces_installer"),
                ),
                subprocess_env_set=(
                    ("BUILD_OUTPUT_DIR", "build/full-build-verification"),
                ),
            ),
            LaneSpec(
                name="redis",
                marker="redis_integration",
                classifier_paths=("services/postgres/tests/test_cache_sync.py",),
                subprocess_paths=("services/postgres/tests/test_cache_sync.py",),
            ),
            LaneSpec(
                name="postgres",
                marker="postgres_integration",
                classifier_path_prefixes=("services/postgres/tests/",),
                classifier_paths=("app/tests/test_checkout_settings_service.py",),
                classifier_class_base_names=(
                    "PostgresTestCase",
                    "SharedPostgresContainerTestCase",
                    "RedisTestCase",
                ),
                subprocess_paths=(
                    "services/postgres/tests",
                    "app/tests/test_checkout_e2e.py",
                    "app/tests/test_config_e2e.py",
                    "app/tests/test_database_schema_ensurer.py",
                    "app/tests/test_checkout_settings_service.py",
                ),
                subprocess_ignore=("services/postgres/tests/test_cache_sync.py",),
            ),
            LaneSpec(
                name="api",
                marker="unit",
                classifier_path_prefixes=("services/api/tests/",),
                subprocess_paths=("services/api/tests",),
            ),
            LaneSpec(
                name="e2e",
                marker="e2e",
                classifier_paths=(
                    "app/tests/test_checkout_e2e.py",
                    "app/tests/test_config_e2e.py",
                    "app/tests/test_database_schema_ensurer.py",
                ),
            ),
            LaneSpec(
                name="acceptance",
                marker="acceptance",
                classifier_path_prefixes=(
                    "experiments/checkout-redesign/acceptance_tests",
                    "tests/backend_acceptance",
                ),
                subprocess_paths=(
                    "experiments/checkout-redesign/acceptance_tests",
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
            "redis",
            "acceptance",
            "api",
            "other",
        ),
        subprocess_order_full=(
            "postgres",
            "redis",
            "acceptance",
            "full_build_verification",
            "api",
            "other",
        ),
    )


_ROOT = Path("C:/repo")
_CONFIG = _example_lane_config()


def test_postgres_tests_are_classified_as_postgres_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "services" / "postgres" / "tests" / "test_order_logger.py",
        nodeid=(
            "services/postgres/tests/test_order_logger.py::"
            "TestOrderLoggerRepository::test_create_order"
        ),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "postgres_integration"


def test_cache_sync_file_is_classified_as_redis_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "services" / "postgres" / "tests" / "test_cache_sync.py",
        nodeid="services/postgres/tests/test_cache_sync.py::test_one",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "redis_integration"


def test_api_directory_tests_are_classified_with_unit_marker() -> None:
    item = _FakeItem(
        path=_ROOT / "services" / "api" / "tests" / "test_order_logger.py",
        nodeid="services/api/tests/test_order_logger.py::test_one",
    )

    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "api"
    assert spec.marker == "unit"


def test_config_e2e_paths_are_classified_as_e2e_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_config_e2e.py",
        nodeid="app/tests/test_config_e2e.py::test_round_trip",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "e2e"


def test_unmatched_tests_fall_back_to_unit_marker_via_other_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_pricing_logic.py",
        nodeid="app/tests/test_pricing_logic.py::test_one",
    )

    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "other"
    assert spec.marker == "unit"


def test_full_build_verification_filename_is_classified_as_fbv_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "test_full_build_verification.py",
        nodeid=("test_full_build_verification.py::test_build_produces_installer"),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "full_build_verification"


def test_acceptance_path_prefix_is_classified_as_acceptance_lane() -> None:
    item = _FakeItem(
        path=_ROOT
        / "tests"
        / "backend_acceptance"
        / "infrastructure"
        / "test_order_totals.py",
        nodeid="tests/backend_acceptance/infrastructure/test_order_totals.py::test_one",
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "acceptance"


def test_checkout_settings_service_is_classified_as_postgres_lane() -> None:
    item = _FakeItem(
        path=_ROOT / "app" / "tests" / "test_checkout_settings_service.py",
        nodeid=(
            "app/tests/test_checkout_settings_service.py::"
            "TestCheckoutSettingsServiceIntegration::"
            "test_save_should_persist_settings_on_fresh_database"
        ),
    )

    assert lane_for_item(item, _ROOT, _CONFIG).marker == "postgres_integration"


def test_class_base_name_promotes_unit_test_into_postgres_lane() -> None:
    postgres_base = type("PostgresTestCase", (), {})
    fake_postgres_test_class = type("TestContainerBacked", (postgres_base,), {})
    item = _FakeItem(
        path=_ROOT / "services" / "api" / "tests" / "test_order_logger.py",
        nodeid="services/api/tests/test_order_logger.py::test_one",
        test_class=fake_postgres_test_class,
    )

    # Class-based assignment wins regardless of file path.
    spec = lane_for_item(item, _ROOT, _CONFIG)
    assert spec.name == "postgres"
