"""Ad-hoc lane construction for ``--lane-def`` and ``--lanes-auto``."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from pytest_lanes.config import LaneConfig, LaneSpec
from pytest_lanes.config_discovery import discover_lane_config
from pytest_lanes.layout import (
    has_root_level_test_files,
    test_bearing_subdirectories,
)

FALLBACK_LANE_NAME = "other"
MINIMUM_USEFUL_PARTITION = 2


def resolve_lane_config_or_none(
    cli_definitions: tuple[str, ...],
    lanes_auto: bool,
    rootpath: Path,
) -> LaneConfig | None:
    """Resolve the active lane config: CLI definitions > auto partition > files."""
    if cli_definitions:
        return lane_config_from_definitions(cli_definitions)
    if lanes_auto:
        auto_config = auto_lane_config_or_none(rootpath)
        if auto_config is not None:
            return auto_config
    return discover_lane_config(rootpath)


def lane_config_from_definitions(definitions: Sequence[str]) -> LaneConfig:
    """Build a LaneConfig from ``name=path[,path...]`` definition strings."""
    lane_specs = [_parse_definition(definition) for definition in definitions]
    _validate_definition_names(lane_specs)
    lane_specs.append(_fallback_lane())

    return LaneConfig(
        lanes=tuple(lane_specs),
        subprocess_order_standard=tuple(spec.name for spec in lane_specs),
    )


def _parse_definition(definition: str) -> LaneSpec:
    name, separator, paths_text = definition.partition("=")
    name = name.strip()
    paths = tuple(path.strip() for path in paths_text.split(",") if path.strip())
    if not separator or not name or not paths:
        raise pytest.UsageError(
            f"--lane-def '{definition}' must be in name=path[,path...] form."
        )

    return LaneSpec(
        name=name,
        marker="",
        classifier_path_prefixes=paths,
        subprocess_paths=paths,
    )


def auto_lane_config_or_none(rootpath: Path) -> LaneConfig | None:
    """Build one lane per test-bearing immediate subdirectory of ``rootpath``."""
    lane_dir_names = [
        directory.name for directory in test_bearing_subdirectories(rootpath)
    ]
    if len(lane_dir_names) < MINIMUM_USEFUL_PARTITION:
        return None

    fallback = _fallback_lane(name=_unclaimed_name(lane_dir_names))
    lane_specs = [
        LaneSpec(
            name=name,
            marker="",
            classifier_path_prefixes=(name,),
            subprocess_paths=(name,),
        )
        for name in lane_dir_names
    ]
    lane_specs.append(fallback)

    order = list(lane_dir_names)
    if has_root_level_test_files(rootpath):
        order.append(fallback.name)

    return LaneConfig(lanes=tuple(lane_specs), subprocess_order_standard=tuple(order))


def _unclaimed_name(taken_names: Sequence[str]) -> str:
    name = FALLBACK_LANE_NAME
    while name in taken_names:
        name = f"{name}_files"
    return name


def _validate_definition_names(lane_specs: Sequence[LaneSpec]) -> None:
    seen: set[str] = set()
    for spec in lane_specs:
        if spec.name == FALLBACK_LANE_NAME:
            raise pytest.UsageError(
                f"--lane-def name '{FALLBACK_LANE_NAME}' is reserved for the "
                "automatic fallback lane."
            )
        if spec.name in seen:
            raise pytest.UsageError(f"--lane-def name '{spec.name}' is defined twice.")
        seen.add(spec.name)


def _fallback_lane(name: str = FALLBACK_LANE_NAME) -> LaneSpec:
    return LaneSpec(
        name=name,
        marker="",
        classifier_fallback=True,
        subprocess_ignore_other_lanes=True,
        tolerate_no_tests=True,
    )
