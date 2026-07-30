"""How a suggested ``[pytest-lanes]`` INI block is spelled."""

from __future__ import annotations

from collections.abc import Sequence


def markers_block(lane_names: Sequence[str], origin: str) -> list[str]:
    """The ``[pytest] markers`` declarations every suggested lane needs."""
    lines = ["[pytest]", "markers ="]
    lines.extend(f"    {name}: {name} lane ({origin})" for name in lane_names)
    return lines


def index_block(lane_names: Sequence[str], scheduled: Sequence[str]) -> list[str]:
    """The ``[pytest-lanes]`` index: every lane, and the ones to launch."""
    return [
        "",
        "[pytest-lanes]",
        f"lanes = {' '.join(lane_names)}",
        f"subprocess_order_standard = {' '.join(scheduled)}",
    ]


def fallback_section(name: str, notes: Sequence[str]) -> list[str]:
    """The catch-all lane, which must tolerate having nothing left to claim."""
    return [
        "",
        f"[pytest-lanes:{name}]",
        *notes,
        f"marker = {name}",
        "classifier_fallback = true",
        "subprocess_ignore_other_lanes = true",
        "tolerate_no_tests = true",
    ]
