"""Per-lane JUnit XML redirection and parent-side merging."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

# The input is our own staged pytest output, so stdlib ElementTree is acceptable.
from xml.etree import ElementTree

from pytest_lanes.constants import lane_filename_token

JUNIT_FLAGS: tuple[str, ...] = ("--junitxml", "--junit-xml")
_VALUE_SEPARATOR = "="
_STAGED_SUFFIX = ".xml"

_SUITES_TAG = "testsuites"
_SUITE_TAG = "testsuite"
_COUNT_ATTRIBUTES = ("errors", "failures", "skipped", "tests")
_TIME_ATTRIBUTE = "time"
_NAME_ATTRIBUTE = "name"
_NAME_INDEX_SEPARATOR = "-"
_XML_DECLARATION = "<?xml version='1.0' encoding='utf-8'?>"


class JunitMergeError(Exception):
    """Raised when a staged junit document is present but unreadable."""


def junit_target_path(args: tuple[str, ...]) -> str | None:
    for token_index, arg in enumerate(args):
        flag = _matched_junit_flag(arg)
        if flag is None:
            continue
        if arg == flag:
            return _value_after(args, token_index)
        return arg[len(flag) + len(_VALUE_SEPARATOR) :]
    return None


def args_with_lane_junit_path(
    args: tuple[str, ...], lane_name: str, staging_dir: Path
) -> tuple[str, ...]:
    staged = lane_junit_path(lane_name, staging_dir)
    redirected: list[str] = []
    skip_value_token = False
    for token_index, arg in enumerate(args):
        if skip_value_token:
            skip_value_token = False
            continue
        flag = _matched_junit_flag(arg)
        if flag is None:
            redirected.append(arg)
            continue
        # The "=" form: one token per flag, no shell quoting question.
        redirected.append(f"{flag}{_VALUE_SEPARATOR}{staged}")
        skip_value_token = arg == flag and _value_after(args, token_index) is not None
    return tuple(redirected)


def lane_junit_path(lane_name: str, staging_dir: Path) -> Path:
    return staging_dir / f"{lane_filename_token(lane_name)}{_STAGED_SUFFIX}"


def merged_junit_document(documents: Sequence[str]) -> str:
    """One ``<testsuites>`` root holding every lane's ``<testsuite>``."""
    suites = _suites_of_every_document(documents)
    _named_distinctly(suites)
    root = ElementTree.Element(_SUITES_TAG)
    _set_rolled_up_totals(root, suites)
    root.extend(suites)
    return _serialized(root)


def _suites_of_every_document(
    documents: Sequence[str],
) -> tuple[ElementTree.Element, ...]:
    suites: list[ElementTree.Element] = []
    for document in documents:
        suites.extend(_suites_of(document))
    return tuple(suites)


def _suites_of(document: str) -> tuple[ElementTree.Element, ...]:
    """The suites of one staged document, or none when nothing was staged."""
    if not document.strip():
        return ()
    root = _parsed(document)
    if root.tag == _SUITE_TAG:
        # Some pytest versions and plugins emit a bare suite with no wrapper.
        return (root,)
    if root.tag == _SUITES_TAG:
        return tuple(root.findall(_SUITE_TAG))
    raise JunitMergeError(
        f"expected a <{_SUITES_TAG}> or <{_SUITE_TAG}> root, found <{root.tag}>"
    )


def _parsed(document: str) -> ElementTree.Element:
    try:
        return ElementTree.fromstring(document)
    except ElementTree.ParseError as error:
        raise JunitMergeError(
            f"staged junit report is not valid XML: {error}"
        ) from error


def _named_distinctly(suites: tuple[ElementTree.Element, ...]) -> None:
    """Number colliding suite names by position: ``pytest-1``, ``pytest-2``."""
    names = [suite.get(_NAME_ATTRIBUTE) for suite in suites]
    colliding = {name for name in names if name is not None and names.count(name) > 1}
    for position, suite in enumerate(suites, start=1):
        name = suite.get(_NAME_ATTRIBUTE)
        if name in colliding:
            suite.set(_NAME_ATTRIBUTE, f"{name}{_NAME_INDEX_SEPARATOR}{position}")


def _set_rolled_up_totals(
    root: ElementTree.Element, suites: tuple[ElementTree.Element, ...]
) -> None:
    """Repeat every suite's totals on the root element."""
    for attribute in _COUNT_ATTRIBUTES:
        root.set(attribute, str(sum(_count_of(suite, attribute) for suite in suites)))
    root.set(_TIME_ATTRIBUTE, f"{sum(_seconds_of(suite) for suite in suites):.3f}")


def _count_of(suite: ElementTree.Element, attribute: str) -> int:
    return int(suite.get(attribute, "0") or "0")


def _seconds_of(suite: ElementTree.Element) -> float:
    return float(suite.get(_TIME_ATTRIBUTE, "0") or "0")


def _serialized(root: ElementTree.Element) -> str:
    """One document, declaration first, byte-identical for equal inputs."""
    body = ElementTree.tostring(root, encoding="unicode")
    return f"{_XML_DECLARATION}\n{body}"


def _matched_junit_flag(arg: str) -> str | None:
    """The junit flag this token spells, if any."""
    for flag in JUNIT_FLAGS:
        if arg == flag or arg.startswith(f"{flag}{_VALUE_SEPARATOR}"):
            return flag
    return None


def _value_after(args: tuple[str, ...], flag_index: int) -> str | None:
    """The token following a bare flag - absent when the flag ends argv."""
    value_index = flag_index + 1
    if value_index >= len(args):
        return None
    return args[value_index]
