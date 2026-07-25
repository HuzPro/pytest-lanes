"""Per-lane JUnit XML redirection and parent-side merging.

The plugin hands the user's unrecognized argv to every lane child, so one
``--junitxml=report.xml`` becomes N children writing the same path: the last
one to finish wins and the report silently describes a fraction of the suite.
The fix is to redirect each child to its own staging path and merge the
staged documents in the parent.

Everything here is pure: functions take argv tuples and XML *text* and
return argv tuples, paths, and XML text. Reading, writing, and process
launching stay in the orchestration shell.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from pathlib import Path

# The documents merged here are pytest's own junit output, staged by this
# plugin moments earlier - not untrusted third-party XML - so stdlib
# ElementTree and its known entity-expansion caveats are acceptable.
from xml.etree import ElementTree

JUNIT_FLAGS: tuple[str, ...] = ("--junitxml", "--junit-xml")
_VALUE_SEPARATOR = "="
_STAGED_SUFFIX = ".xml"
_UNSAFE_IN_FILENAME = re.compile(r"[^A-Za-z0-9_-]+")
_UNNAMED_LANE = "lane"

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
        # Always the "=" form: one token per flag is less for the child
        # argv, and the shell quoting question disappears with it.
        redirected.append(f"{flag}{_VALUE_SEPARATOR}{staged}")
        skip_value_token = arg == flag and _value_after(args, token_index) is not None
    return tuple(redirected)


def lane_junit_path(lane_name: str, staging_dir: Path) -> Path:
    return staging_dir / f"{_filename_token(lane_name)}{_STAGED_SUFFIX}"


def merged_junit_document(documents: Sequence[str]) -> str:
    """One ``<testsuites>`` root holding every lane's ``<testsuite>``.

    Several ``<testsuite>`` elements under one root is standard JUnit and
    is what CI consumers already understand, so lanes stay individually
    visible instead of being flattened into one indistinguishable suite.
    """
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
    """The suites of one staged document, or none when nothing was staged.

    A lane that died before writing its report leaves an empty file: a
    partial report is worth more than no report, so that lane is skipped.
    Content that is present but unparseable is a different story - it is
    evidence of a real problem and must not disappear quietly.
    """
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
    """Number colliding suite names by position: ``pytest-1``, ``pytest-2``.

    Every lane's suite is called ``pytest``, and a consumer that keys on
    the suite name would show one lane and drop the rest. Names that are
    already unique are left exactly as the child wrote them.
    """
    names = [suite.get(_NAME_ATTRIBUTE) for suite in suites]
    colliding = {name for name in names if name is not None and names.count(name) > 1}
    for position, suite in enumerate(suites, start=1):
        name = suite.get(_NAME_ATTRIBUTE)
        if name in colliding:
            suite.set(_NAME_ATTRIBUTE, f"{name}{_NAME_INDEX_SEPARATOR}{position}")


def _set_rolled_up_totals(
    root: ElementTree.Element, suites: tuple[ElementTree.Element, ...]
) -> None:
    """Repeat every suite's totals on the root element.

    Plenty of CI consumers read only the root attributes; a root without
    them reports a suite of zero tests no matter what the children say.
    """
    for attribute in _COUNT_ATTRIBUTES:
        root.set(attribute, str(sum(_count_of(suite, attribute) for suite in suites)))
    root.set(_TIME_ATTRIBUTE, f"{sum(_seconds_of(suite) for suite in suites):.3f}")


def _count_of(suite: ElementTree.Element, attribute: str) -> int:
    return int(suite.get(attribute, "0") or "0")


def _seconds_of(suite: ElementTree.Element) -> float:
    return float(suite.get(_TIME_ATTRIBUTE, "0") or "0")


def _serialized(root: ElementTree.Element) -> str:
    """One document, declaration first, byte-identical for equal inputs.

    Attribute order follows insertion order in every supported Python, so
    building the tree deterministically is enough to make the text stable.
    """
    body = ElementTree.tostring(root, encoding="unicode")
    return f"{_XML_DECLARATION}\n{body}"


def _filename_token(lane_name: str) -> str:
    """Reduce a lane name to something safe to put in a filename.

    Sharded lanes are named ``postgres~1of2``, and lane names come from a
    user's INI file, so they can carry separators and shell metacharacters
    that have no business in a path.
    """
    token = _UNSAFE_IN_FILENAME.sub("_", lane_name).strip("_")
    return token or _UNNAMED_LANE


def _matched_junit_flag(arg: str) -> str | None:
    """The junit flag this token spells, if any.

    Matching on the exact token or on ``flag=`` keeps an unrelated argument
    that merely shares a prefix (``--junitxmlish``) from being claimed.
    """
    for flag in JUNIT_FLAGS:
        if arg == flag or arg.startswith(f"{flag}{_VALUE_SEPARATOR}"):
            return flag
    return None


def _value_after(args: tuple[str, ...], flag_index: int) -> str | None:
    """The token following a bare flag - absent when the flag ends argv.

    A trailing valueless flag is pytest's error to report, not ours.
    """
    value_index = flag_index + 1
    if value_index >= len(args):
        return None
    return args[value_index]
