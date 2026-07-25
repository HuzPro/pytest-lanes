"""Per-lane coverage data files and parent-side report generation.

``--cov`` reaches every lane child through the passthrough argv, and every
child then writes the same ``.coverage`` SQLite file. Concurrent writers
corrupt it: coverage.py raises ``DataError: no such table: other_db.file``,
which surfaces as a lane failure even when every test passed. Worse, each
child would also emit its own partial report.

The fix is a three-part contract this module supplies the pieces for: point
each child at its own ``COVERAGE_FILE``, strip the report requests from the
child argv so only measurement happens there, and hand the parent the
``coverage`` commands to run once the data files have been combined.

Everything here is pure - argv tuples and strings in, argv tuples and
strings out. Combining and running belong to the orchestration shell.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

COVERAGE_DATA_ENV = "COVERAGE_FILE"

_COV_FLAG = "--cov"
_COV_REPORT_FLAG = "--cov-report"
_VALUE_SEPARATOR = "="
_OPTION_SEPARATOR = "-"
# coverage.py's own convention: ``combine`` discovers parallel data files by
# this prefix, so a lane file named anything else would never be combined.
_DATA_FILE_PREFIX = ".coverage."
_DESTINATION_SEPARATOR = ":"
_OUTPUT_FILE_FLAG = "-o"
_OUTPUT_DIRECTORY_FLAG = "-d"
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")
_UNNAMED_LANE = "lane"


def is_coverage_requested(args: tuple[str, ...]) -> bool:
    return any(_is_coverage_option(arg) for arg in args)


def lane_coverage_env(lane_name: str, data_dir: Path) -> tuple[tuple[str, str], ...]:
    """The environment override that isolates one lane's measurements.

    Returned as name/value pairs rather than applied, so the caller decides
    which child environment it belongs to.
    """
    data_file = data_dir / f"{_DATA_FILE_PREFIX}{_filename_token(lane_name)}"
    return ((COVERAGE_DATA_ENV, str(data_file)),)


def args_without_coverage_reports(args: tuple[str, ...]) -> tuple[str, ...]:
    """The child argv with every report request removed, measurement intact.

    A child that reports describes only the tests its own lane ran, so N
    lanes print N partial summaries and overwrite each other's files.
    ``--cov`` and the other measurement options stay: without them the
    child collects no data for the parent to combine.
    """
    dropped = {
        index for request in _report_requests(args) for index in request.token_indices
    }
    return tuple(arg for index, arg in enumerate(args) if index not in dropped)


def requested_coverage_reports(args: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(request.value for request in _report_requests(args))


def coverage_report_command(report: str) -> tuple[str, ...] | None:
    """The ``coverage`` argv tail that produces one pytest-cov report.

    Absent when the spec is not one this module models: the parent skips
    that report rather than guessing and emitting the wrong thing, and one
    exotic spec never costs the run its other reports.
    """
    kind_name, _, destination = report.partition(_DESTINATION_SEPARATOR)
    kind = _REPORT_KINDS.get(kind_name)
    if kind is None:
        return None
    if not destination:
        return kind.command
    if not kind.destination_flag:
        return None
    return (*kind.command, kind.destination_flag, destination)


@dataclass(frozen=True)
class _ReportKind:
    """How one pytest-cov report kind is spelled as a coverage command.

    An empty ``destination_flag`` marks a kind that accepts no destination;
    anything after the colon there is a modifier this module does not model.
    """

    command: tuple[str, ...]
    destination_flag: str = ""


_REPORT_KINDS: Mapping[str, _ReportKind] = {
    # An empty spec is the plain terminal report *here*, but note that
    # pytest-cov reads a bare "--cov-report=" as asking for no report at
    # all: a caller honouring that must drop empty specs before asking.
    "": _ReportKind(("report",)),
    "term": _ReportKind(("report",)),
    "term-missing": _ReportKind(("report", "--show-missing")),
    "xml": _ReportKind(("xml",), _OUTPUT_FILE_FLAG),
    "json": _ReportKind(("json",), _OUTPUT_FILE_FLAG),
    "lcov": _ReportKind(("lcov",), _OUTPUT_FILE_FLAG),
    "html": _ReportKind(("html",), _OUTPUT_DIRECTORY_FLAG),
    "annotate": _ReportKind(("annotate",), _OUTPUT_DIRECTORY_FLAG),
}


@dataclass(frozen=True)
class _ReportRequest:
    """One ``--cov-report`` occurrence: what it asks for, and where it sits."""

    token_indices: tuple[int, ...]
    value: str


def _report_requests(args: tuple[str, ...]) -> tuple[_ReportRequest, ...]:
    """Locate every report request, in the order the user wrote them.

    Both spellings are found here so that stripping and collecting can
    never disagree about which tokens belong to a request.
    """
    joined_prefix = f"{_COV_REPORT_FLAG}{_VALUE_SEPARATOR}"
    requests: list[_ReportRequest] = []
    for index, arg in enumerate(args):
        if arg == _COV_REPORT_FLAG:
            requests.append(_separate_token_request(args, index))
        elif arg.startswith(joined_prefix):
            requests.append(_ReportRequest((index,), arg[len(joined_prefix) :]))
    return tuple(requests)


def _separate_token_request(args: tuple[str, ...], flag_index: int) -> _ReportRequest:
    """Claim the following token as the value, the way argparse would.

    A flag that ends argv has no value to claim; pytest rejects that
    invocation itself, so an empty value is enough of an answer here.
    """
    value_index = flag_index + 1
    if value_index >= len(args):
        return _ReportRequest((flag_index,), "")
    return _ReportRequest((flag_index, value_index), args[value_index])


def _filename_token(lane_name: str) -> str:
    """Reduce a lane name to something safe to put in a filename.

    Sharded lanes are named ``postgres~1of2``, and lane names come from a
    user's INI file, so they can carry separators and shell metacharacters
    that have no business in a path.
    """
    token = _UNSAFE_IN_FILENAME.sub("_", lane_name).strip("_")
    return token or _UNNAMED_LANE


def _is_coverage_option(arg: str) -> bool:
    """Whether one token is a pytest-cov option.

    The token has to be ``--cov`` exactly, or ``--cov`` followed by a
    separator - otherwise a bare prefix test would also claim unrelated
    options that happen to begin with the same letters.
    """
    if arg == _COV_FLAG:
        return True
    return arg.startswith(
        (f"{_COV_FLAG}{_VALUE_SEPARATOR}", f"{_COV_FLAG}{_OPTION_SEPARATOR}")
    )
