"""Behavioral tests for static shard planning."""

from __future__ import annotations

from pathlib import Path

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.durations import LaneRecord
from pytest_lanes.sharding import (
    load_persisted_plan,
    persist_first_shard,
    plan_shards,
    simulate_makespan,
)


def _divisible_config(shard_min_saving: float = 5.0) -> LaneConfig:
    return LaneConfig(
        lanes=(
            LaneSpec(
                name="postgres",
                marker="postgres_integration",
                classifier_path_prefixes=("db/",),
                subprocess_paths=("db",),
                divisible=True,
            ),
            LaneSpec(
                name="other",
                marker="unit",
                classifier_fallback=True,
                subprocess_ignore_other_lanes=True,
            ),
        ),
        subprocess_order_standard=("postgres", "other"),
        shard_min_saving=shard_min_saving,
    )


_RECORDS = {
    "postgres": LaneRecord(
        total=30.0,
        startup=2.0,
        collect=1.0,
        files=(
            ("db/test_a.py", 7.0),
            ("db/test_b.py", 7.0),
            ("db/test_c.py", 7.0),
            ("db/test_d.py", 6.0),
        ),
    ),
    "other": LaneRecord(total=4.0),
}


def _plan(records=_RECORDS, max_workers=4, config=None, file_exists=lambda p: True):
    return plan_shards(
        mode="standard",
        passthrough_args=(),
        lane_config=config or _divisible_config(),
        records=records,
        max_workers=max_workers,
        file_exists=file_exists,
    )


def test_planner_splits_the_longest_divisible_lane_when_gain_clears_threshold() -> None:
    plan = _plan()

    names = [command.name for command in plan.commands]
    assert names == ["postgres~1of2", "postgres~2of2", "other"]

    first, second = plan.commands[0], plan.commands[1]
    assert "db/test_a.py" in first.args
    assert "db/test_b.py" in first.args
    assert "db" in second.args
    assert "--ignore=db/test_a.py" in second.args
    assert "--ignore=db/test_b.py" in second.args
    assert second.tolerate_no_tests is True
    assert plan.sharded_lane == "postgres"
    assert any("sharded postgres into 2" in note for note in plan.notes)


def test_planner_declines_when_any_scheduled_lane_lacks_a_record() -> None:
    plan = _plan(records={"postgres": _RECORDS["postgres"]})

    assert [command.name for command in plan.commands] == ["postgres", "other"]
    assert plan.sharded_lane == ""


def test_planner_declines_when_the_pool_has_no_room_for_a_second_shard() -> None:
    plan = _plan(max_workers=1)

    assert [command.name for command in plan.commands] == ["postgres", "other"]


def test_planner_never_touches_lanes_that_did_not_opt_in() -> None:
    config = _divisible_config()
    undeclared = LaneConfig(
        lanes=tuple(
            LaneSpec(**{**spec.__dict__, "divisible": False}) for spec in config.lanes
        ),
        subprocess_order_standard=config.subprocess_order_standard,
        shard_min_saving=config.shard_min_saving,
    )

    plan = _plan(config=undeclared)

    assert [command.name for command in plan.commands] == ["postgres", "other"]
    assert plan.notes == ()


def _plan_with_persisted(persisted: tuple[str, ...]):
    return plan_shards(
        mode="standard",
        passthrough_args=(),
        lane_config=_divisible_config(),
        records=_RECORDS,
        max_workers=4,
        file_exists=lambda path: True,
        persisted_plan=("postgres", persisted),
    )


def test_persisted_cut_is_reused_while_it_stays_balanced() -> None:
    # 14s vs 13s: within the 20% ratio, the sticky cut wins.
    plan = _plan_with_persisted(("db/test_a.py", "db/test_c.py"))

    assert plan.first_shard_files == ("db/test_a.py", "db/test_c.py")
    assert not any("re-cut" in note for note in plan.notes)


def test_drifted_durations_trigger_a_loud_recut() -> None:
    # 21s vs 6s: 71% imbalance forces a loud re-cut.
    plan = _plan_with_persisted(("db/test_a.py", "db/test_b.py", "db/test_c.py"))

    assert plan.first_shard_files == ("db/test_a.py", "db/test_b.py")
    assert any("re-cut" in note for note in plan.notes)


def test_vanished_files_are_excluded_from_the_explicit_shard() -> None:
    plan = _plan(file_exists=lambda path: path != "db/test_a.py")

    first = plan.commands[0]
    assert "db/test_a.py" not in first.args
    assert any("db/test_a.py" not in command.args for command in plan.commands[:1])


def test_shard_results_merge_back_into_the_parent_lane_record(tmp_path: Path) -> None:
    import json

    from pytest_lanes import executor
    from pytest_lanes.durations import InMemoryDurationStore
    from pytest_lanes.reporter import LaneProgressReporter

    reporter = LaneProgressReporter(clock=lambda: 0.0)
    reporter.register_lanes(["postgres~1of2", "postgres~2of2", "other"])
    for name in ("postgres~1of2", "postgres~2of2", "other"):
        reporter.mark_started(name)
        reporter.mark_finished(name, exit_code=0)
    for lane in reporter._lanes.values():
        lane.duration = 10.0
    (tmp_path / "postgres~1of2.json").write_text(
        json.dumps(
            {
                "startup": 2.0,
                "collect": 1.0,
                "files": {"db/test_a.py": 7.0},
                "total": 10.0,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "postgres~2of2.json").write_text(
        json.dumps(
            {
                "startup": 2.5,
                "collect": 1.0,
                "files": {"db/test_b.py": 6.0},
                "total": 9.5,
            }
        ),
        encoding="utf-8",
    )
    store = InMemoryDurationStore()

    executor._record_run_durations(
        reporter,
        store,
        tmp_path,
        shard_parents={"postgres~1of2": "postgres", "postgres~2of2": "postgres"},
    )

    records = store.recorded_lane_records()
    assert set(records) == {"postgres", "other"}
    postgres = records["postgres"]
    assert dict(postgres.files) == {"db/test_a.py": 7.0, "db/test_b.py": 6.0}
    assert postgres.startup == 2.5
    # Parent total approximates the unsharded serial run.
    assert postgres.total == 2.5 + 1.0 + 13.0


def test_persisted_plan_round_trips(tmp_path: Path) -> None:
    path = tmp_path / "shard_plan.json"

    persist_first_shard(path, "postgres", ("db/test_a.py", "db/test_b.py"))

    assert load_persisted_plan(path) == (
        "postgres",
        ("db/test_a.py", "db/test_b.py"),
    )


def test_persisted_plan_for_a_different_lane_is_ignored_by_the_planner() -> None:
    plan = plan_shards(
        mode="standard",
        passthrough_args=(),
        lane_config=_divisible_config(),
        records=_RECORDS,
        max_workers=4,
        file_exists=lambda path: True,
        persisted_plan=("redis", ("db/test_a.py", "db/test_b.py", "db/test_c.py")),
    )

    # A stale plan for another lane cannot steer this lane's cut.
    assert plan.first_shard_files == ("db/test_a.py", "db/test_b.py")
    assert not any("re-cut" in note for note in plan.notes)


def test_corrupt_persisted_plan_reads_as_none(tmp_path: Path) -> None:
    path = tmp_path / "shard_plan.json"
    path.write_text("{broken", encoding="utf-8")

    assert load_persisted_plan(path) is None


def test_single_worker_makespan_is_the_sum_of_lane_durations() -> None:
    assert simulate_makespan([10.0, 5.0, 3.0], max_workers=1) == 18.0


def test_unbounded_workers_makespan_is_the_longest_lane() -> None:
    assert simulate_makespan([10.0, 5.0, 3.0], max_workers=8) == 10.0


def test_bounded_pool_queues_lanes_longest_first_onto_freed_slots() -> None:
    # W=2 longest-first: 10 bounds the makespan.
    assert simulate_makespan([5.0, 10.0, 3.0], max_workers=2) == 10.0

    # W=2, order 8,7,6: 8 and 7 start; 7 frees at t=7, 6 runs to t=13.
    assert simulate_makespan([6.0, 7.0, 8.0], max_workers=2) == 13.0


def test_no_lanes_means_zero_makespan() -> None:
    assert simulate_makespan([], max_workers=4) == 0.0
