"""Behavioral tests for the duration-balanced lane partition."""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.balance import (
    BalancedLane,
    balanced_partition,
    format_balanced_suggestion,
)
from pytest_lanes.config import load_lane_config
from pytest_lanes.durations import LaneRecord


def test_pooling_keeps_the_slowest_recorded_seconds_for_a_duplicated_file() -> None:
    # Arrange: one file measured in two lanes, slower in the second.
    records = {
        "alpha": LaneRecord(
            total=9.0,
            files=(("pkg/test_shared.py", 3.0), ("pkg/test_alpha.py", 6.0)),
        ),
        "beta": LaneRecord(
            total=11.0,
            files=(("pkg/test_shared.py", 8.0), ("other/test_beta.py", 3.0)),
        ),
    }

    # Act
    lanes = balanced_partition(records, lane_count=2)

    # Assert
    pooled = dict(entry for lane in lanes for entry in lane.files)
    assert pooled["pkg/test_shared.py"] == 8.0
    assert sorted(pooled) == [
        "other/test_beta.py",
        "pkg/test_alpha.py",
        "pkg/test_shared.py",
    ]


def test_partition_is_empty_when_fewer_than_two_files_were_recorded() -> None:
    # Arrange: one lane with a single file, plus a totals-only v1 record.
    records = {
        "solo": LaneRecord(total=12.0, files=(("pkg/test_only.py", 12.0),)),
        "unmeasured": LaneRecord(total=30.0),
    }

    # Act
    lanes = balanced_partition(records, lane_count=4)

    # Assert: nothing to balance, and saying so beats inventing a split.
    assert lanes == ()


def _four_equal_directories() -> dict[str, LaneRecord]:
    return {
        "all": LaneRecord(
            total=40.0,
            files=(
                ("alpha/test_one.py", 6.0),
                ("alpha/test_two.py", 4.0),
                ("beta/test_one.py", 6.0),
                ("beta/test_two.py", 4.0),
                ("gamma/test_one.py", 6.0),
                ("gamma/test_two.py", 4.0),
                ("delta/test_one.py", 6.0),
                ("delta/test_two.py", 4.0),
            ),
        )
    }


def test_lanes_carry_roughly_equal_projected_seconds() -> None:
    # Arrange: four directories of 10s each, two lanes to fill.
    records = _four_equal_directories()

    # Act
    lanes = balanced_partition(records, lane_count=2)

    # Assert
    assert len(lanes) == 2
    heaviest = max(lane.projected_seconds for lane in lanes)
    lightest = min(lane.projected_seconds for lane in lanes)
    assert (heaviest - lightest) / heaviest <= 0.10
    assert sum(len(lane.files) for lane in lanes) == 8


def test_partition_is_identical_for_the_same_records_in_a_different_order() -> None:
    # Arrange: the same measurements, walked in a different dict/file order.
    forward = _four_equal_directories()
    shuffled = {
        "all": LaneRecord(
            total=40.0,
            files=tuple(reversed(forward["all"].files)),
        ),
        "empty": LaneRecord(total=1.0),
    }

    # Act
    first = balanced_partition(forward, lane_count=2)
    second = balanced_partition(shuffled, lane_count=2)

    # Assert: ordering must never leak into the result.
    assert first == balanced_partition(forward, lane_count=2)
    assert first == second


def _one_dominant_directory() -> dict[str, LaneRecord]:
    """70s in one directory, 15s each in two others - 100s in total."""
    dominant = tuple((f"misc/test_{index}.py", 10.0) for index in range(1, 8))
    return {
        "misc": LaneRecord(total=70.0, files=dominant),
        "sides": LaneRecord(
            total=30.0,
            files=(
                ("alpha/test_one.py", 8.0),
                ("alpha/test_two.py", 7.0),
                ("beta/test_one.py", 8.0),
                ("beta/test_two.py", 7.0),
            ),
        ),
    }


def test_oversized_directory_is_split_across_lanes_file_by_file() -> None:
    # Arrange: one directory holds 70% of the measured time.
    records = _one_dominant_directory()

    # Act
    lanes = balanced_partition(records, lane_count=3)

    # Assert: the dominant directory is spread, and no lane runs away.
    lanes_holding_misc = [
        lane
        for lane in lanes
        if any(path.startswith("misc/") for path, _ in lane.files)
    ]
    assert len(lanes_holding_misc) == 3
    target_seconds = 100.0 / 3
    assert max(lane.projected_seconds for lane in lanes) <= 1.3 * target_seconds


def test_small_directories_travel_whole_and_are_reported_for_prefix_matching() -> None:
    # Arrange: two small directories beside one dominant directory.
    records = _one_dominant_directory()

    # Act
    lanes = balanced_partition(records, lane_count=3)

    # Assert: whole directories claim by prefix; the split one cannot.
    whole = {directory for lane in lanes for directory in lane.whole_directories}
    assert whole == {"alpha", "beta"}
    for lane in lanes:
        claimed = {path for path, _ in lane.files}
        for directory in lane.whole_directories:
            assert {
                path
                for record in records.values()
                for path, _ in record.files
                if path.startswith(f"{directory}/")
            } <= claimed


def test_lane_is_named_after_its_heaviest_directory() -> None:
    # Arrange: one lane will hold both directories.
    records = {
        "mixed": LaneRecord(
            total=35.0,
            files=(
                ("heavy_suite/test_one.py", 30.0),
                ("light_suite/test_one.py", 5.0),
            ),
        )
    }

    # Act
    lanes = balanced_partition(records, lane_count=1)

    # Assert
    assert [lane.name for lane in lanes] == ["heavy_suite"]


def test_lane_names_are_sanitized_into_marker_safe_tokens() -> None:
    # Arrange: directory names a pytest marker expression cannot hold.
    records = {
        "odd": LaneRecord(
            total=20.0,
            files=(
                ("services/api-v2 (beta)/test_one.py", 12.0),
                ("2fa/test_one.py", 8.0),
            ),
        )
    }

    # Act
    lanes = balanced_partition(records, lane_count=2)

    # Assert: names are usable verbatim as markers and INI section names.
    assert [lane.name for lane in lanes] == ["api_v2_beta", "lane_2fa"]


def test_colliding_lane_names_are_numbered_and_never_shadow_the_rest_lane() -> None:
    # Arrange: two directories share a basename, a third is called "rest".
    records = {
        "twins": LaneRecord(
            total=54.0,
            files=(
                ("services/checkout/test_one.py", 20.0),
                ("workers/checkout/test_one.py", 18.0),
                ("rest/test_one.py", 16.0),
            ),
        )
    }

    # Act
    lanes = balanced_partition(records, lane_count=3)

    # Assert: numbering follows projected seconds; "rest" stays reserved.
    assert [lane.name for lane in lanes] == ["checkout", "checkout_2", "rest_2"]


def test_lanes_are_dropped_rather_than_returned_empty() -> None:
    # Arrange: seven directories of 10s each, eight lanes asked for.
    files = tuple((f"dir_{index}/test_one.py", 10.0) for index in range(1, 7))
    records = {
        "spread": LaneRecord(
            total=70.0,
            files=(
                *files,
                ("dir_7/test_one.py", 5.0),
                ("dir_7/test_two.py", 5.0),
            ),
        )
    }

    # Act
    lanes = balanced_partition(records, lane_count=8)

    # Assert: a declared lane that collects nothing fails the run.
    assert len(lanes) == 7
    assert all(lane.files for lane in lanes)


def test_nothing_is_printed_when_there_is_no_partition_to_suggest() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(())

    # Assert: an empty INI block would read as advice; silence does not.
    assert suggestion == ""


def _two_balanced_lanes() -> tuple[BalancedLane, ...]:
    return (
        BalancedLane(
            name="checkout",
            files=(
                ("misc/test_odds.py", 12.3),
                ("services/checkout/test_cart.py", 30.0),
            ),
            projected_seconds=42.3,
            whole_directories=("services/checkout",),
        ),
        BalancedLane(
            name="billing",
            files=(("misc/test_ends.py", 20.0),),
            projected_seconds=20.0,
            whole_directories=(),
        ),
    )


def test_header_says_where_the_numbers_came_from_and_what_a_lane_costs() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(_two_balanced_lanes())

    # Assert: the header says measured, stale-able, and startup is re-paid.
    assert "recorded" in suggestion
    assert "62.3s across 3 files" in suggestion
    assert "startup" in suggestion
    assert "--lanes-explain" in suggestion
    # Windows consoles with legacy code pages mangle non-ASCII output.
    assert suggestion.isascii()


def test_header_warns_that_shared_service_tests_must_stay_in_one_lane() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(_two_balanced_lanes())

    # Assert: the balancer sees durations only, not shared-service coupling.
    assert "shared external service" in suggestion
    assert "same lane" in suggestion


def test_every_lane_is_declared_as_a_marker_and_listed_in_the_index() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(_two_balanced_lanes())

    # Assert: heaviest lane launches first, catch-all last.
    assert "markers =\n" in suggestion
    assert "    checkout: " in suggestion
    assert "    billing: " in suggestion
    assert "    rest: " in suggestion
    assert "lanes = checkout billing rest" in suggestion
    assert "subprocess_order_standard = checkout billing rest" in suggestion


def test_lane_section_carries_its_projection_paths_and_divisible_assertion() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(_two_balanced_lanes())

    # Assert: directories claim by prefix, split files by name; subprocess_paths mirrors both.
    assert "[pytest-lanes:checkout]" in suggestion
    assert "# projected: 42.3s" in suggestion
    assert "marker = checkout" in suggestion
    assert "divisible = files" in suggestion
    assert "mutually independent" in suggestion
    assert "environment can run duplicated" in suggestion
    assert "classifier_path_prefixes = services/checkout/" in suggestion
    assert "classifier_paths = misc/test_odds.py" in suggestion
    assert "subprocess_paths = services/checkout misc/test_odds.py" in suggestion
    # A lane with no whole directory lists only files.
    assert "classifier_paths = misc/test_ends.py" in suggestion


def test_rest_lane_catches_tests_added_since_the_durations_were_recorded() -> None:
    # Arrange / Act
    suggestion = format_balanced_suggestion(_two_balanced_lanes())

    # Assert: an empty catch-all is success, not a failed run.
    assert "[pytest-lanes:rest]" in suggestion
    assert "marker = rest" in suggestion
    assert "classifier_fallback = true" in suggestion
    assert "subprocess_ignore_other_lanes = true" in suggestion
    assert suggestion.endswith("tolerate_no_tests = true")


def test_printed_block_is_lane_configuration_the_loader_accepts(
    tmp_path: Path,
) -> None:
    # Arrange: paste the suggestion into a pytest.ini, as a user would.
    ini_path = tmp_path / "pytest.ini"
    ini_path.write_text(
        format_balanced_suggestion(_two_balanced_lanes()) + "\n", encoding="utf-8"
    )

    # Act
    config = load_lane_config(ini_path)

    # Assert: "paste-ready" has to mean it loads, markers and all.
    assert [lane.name for lane in config.lanes] == ["checkout", "billing", "rest"]
    assert config.subprocess_order_standard == ("checkout", "billing", "rest")
    checkout = config.lane_by_name("checkout")
    assert checkout is not None
    assert checkout.divisible is True
    assert checkout.classifier_path_prefixes == ("services/checkout/",)
    fallback = config.fallback_lane()
    assert fallback is not None
    assert fallback.name == "rest"
