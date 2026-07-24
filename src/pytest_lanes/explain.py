"""Formatting for ``--lanes-explain`` output.

Turns the :class:`~pytest_lanes.lanes.LaneAssignment` produced for each
collected item into the listing printed after collection: one line per test
showing its lane and the classifier rule that claimed it, plus a totals line.
"""

from __future__ import annotations

from collections.abc import Sequence

from pytest_lanes.lanes import LaneAssignment

EXPLAIN_TITLE = "Lane classification"


def format_lane_explanation(entries: Sequence[tuple[str, LaneAssignment]]) -> str:
    lines = [EXPLAIN_TITLE]
    for node_id, assignment in entries:
        lines.append(f"{node_id} -> {assignment.lane.name} ({_rule_text(assignment)})")

    lane_names = {assignment.lane.name for _, assignment in entries}
    lines.append(f"{len(entries)} tests in {len(lane_names)} lanes")
    return "\n".join(lines)


def _rule_text(assignment: LaneAssignment) -> str:
    if not assignment.matched_value:
        return assignment.rule_kind
    return f"{assignment.rule_kind}: {assignment.matched_value}"
