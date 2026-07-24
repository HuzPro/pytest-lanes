"""Lane configuration schema and INI loader.

The plugin reads its lane definitions from ``[pytest-lanes]`` and
``[pytest-lanes:<name>]`` sections inside the host project's INI file
(``pytest.ini``, ``tox.ini``, or ``setup.cfg`` — the first one at rootdir
that declares the section wins). This module turns that INI text into
immutable :class:`LaneSpec` and :class:`LaneConfig` dataclasses and validates
every cross-reference (marker declarations, subprocess order names,
ignore-other-lanes uniqueness).

Lane markers must be declared in the same file, in ``[pytest].markers``
(``[tool:pytest].markers`` for ``setup.cfg``).
"""

from __future__ import annotations

import configparser
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


class LaneConfigError(Exception):
    """Raised when lane configuration is missing or malformed."""


CONFIG_FILENAMES = ("pytest.ini", "tox.ini", "setup.cfg")


@dataclass(frozen=True)
class LaneSpec:
    name: str
    marker: str
    classifier_paths: tuple[str, ...] = ()
    classifier_path_prefixes: tuple[str, ...] = ()
    classifier_path_suffix: str | None = None
    classifier_class_base_names: tuple[str, ...] = ()
    classifier_fallback: bool = False
    subprocess_paths: tuple[str, ...] = ()
    subprocess_nodeids: tuple[str, ...] = ()
    subprocess_ignore: tuple[str, ...] = ()
    subprocess_ignore_other_lanes: bool = False
    subprocess_env_set: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class LaneConfig:
    lanes: tuple[LaneSpec, ...]
    subprocess_order_standard: tuple[str, ...] = ()
    subprocess_order_full: tuple[str, ...] = ()
    max_workers: int | None = None

    def lane_by_name(self, name: str) -> LaneSpec | None:
        for spec in self.lanes:
            if spec.name == name:
                return spec
        return None

    def standard_subprocess_lanes(self) -> tuple[LaneSpec, ...]:
        return self._lanes_in_order(self.subprocess_order_standard)

    def full_subprocess_lanes(self) -> tuple[LaneSpec, ...]:
        order = self.subprocess_order_full or self.subprocess_order_standard
        return self._lanes_in_order(order)

    def fallback_lane(self) -> LaneSpec | None:
        for spec in self.lanes:
            if spec.classifier_fallback:
                return spec
        return None

    def _lanes_in_order(self, order: tuple[str, ...]) -> tuple[LaneSpec, ...]:
        result: list[LaneSpec] = []
        for name in order:
            spec = self.lane_by_name(name)
            if spec is not None:
                result.append(spec)
        return tuple(result)


def load_lane_config(ini_path: Path) -> LaneConfig:
    parser = configparser.ConfigParser()
    parser.read(ini_path, encoding="utf-8")

    if not parser.has_section("pytest-lanes"):
        raise LaneConfigError(
            f"No [pytest-lanes] section in {ini_path}; the plugin requires lane configuration."
        )

    declared_markers = _parse_declared_markers(parser)
    lane_names = _tokens(parser.get("pytest-lanes", "lanes", fallback=""))
    if not lane_names:
        raise LaneConfigError("[pytest-lanes].lanes must declare at least one lane.")

    lanes = tuple(_parse_lane(parser, name, declared_markers) for name in lane_names)

    _validate_ignore_other_lanes_uniqueness(lanes)

    subprocess_order_standard = _tokens(
        parser.get("pytest-lanes", "subprocess_order_standard", fallback="")
    )
    subprocess_order_full = _tokens(
        parser.get("pytest-lanes", "subprocess_order_full", fallback="")
    )
    _validate_subprocess_order_names(
        subprocess_order_standard, lane_names, "subprocess_order_standard"
    )
    _validate_subprocess_order_names(
        subprocess_order_full, lane_names, "subprocess_order_full"
    )

    return LaneConfig(
        lanes=lanes,
        subprocess_order_standard=subprocess_order_standard,
        subprocess_order_full=subprocess_order_full,
        max_workers=_parse_max_workers(parser),
    )


def _parse_max_workers(parser: configparser.ConfigParser) -> int | None:
    text = parser.get("pytest-lanes", "max_workers", fallback="").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError as error:
        raise LaneConfigError(
            f"[pytest-lanes].max_workers must be an integer (got '{text}')."
        ) from error


def load_lane_config_or_none(rootpath: Path) -> LaneConfig | None:
    """Load lane config from the first rootdir INI file declaring ``[pytest-lanes]``.

    Returns ``None`` when no candidate file declares the section — the plugin
    stays dormant and pytest behaves as if it were not installed. Malformed
    sections still raise :class:`LaneConfigError` so mistakes surface loudly.
    """
    for filename in CONFIG_FILENAMES:
        candidate = rootpath / filename
        if not candidate.exists():
            continue
        parser = configparser.ConfigParser()
        parser.read(candidate, encoding="utf-8")
        if parser.has_section("pytest-lanes"):
            return load_lane_config(candidate)
    return None


def _parse_declared_markers(parser: configparser.ConfigParser) -> set[str]:
    # pytest.ini and tox.ini declare markers under [pytest]; setup.cfg uses
    # [tool:pytest].
    markers_text = ""
    for section in ("pytest", "tool:pytest"):
        if parser.has_section(section):
            markers_text = parser.get(section, "markers", fallback="")
            break
    declared: set[str] = set()
    for line in markers_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        # pytest marker syntax is "name: description"; allow no description too.
        name = stripped.split(":", 1)[0].strip()
        if name:
            declared.add(name)
    return declared


def _parse_lane(
    parser: configparser.ConfigParser,
    name: str,
    declared_markers: set[str],
) -> LaneSpec:
    section = f"pytest-lanes:{name}"
    if not parser.has_section(section):
        raise LaneConfigError(
            f"Lane '{name}' is declared in [pytest-lanes].lanes but has no [{section}] section."
        )

    marker = parser.get(section, "marker", fallback="").strip()
    if not marker:
        raise LaneConfigError(f"Lane '{name}' is missing the required 'marker' field.")
    if marker not in declared_markers:
        raise LaneConfigError(
            f"Lane '{name}' uses marker '{marker}' which is not declared in [pytest].markers."
        )

    env_set_pairs = tuple(
        _parse_env_set(parser.get(section, "subprocess_env_set", fallback=""))
    )

    return LaneSpec(
        name=name,
        marker=marker,
        classifier_paths=_tokens(parser.get(section, "classifier_paths", fallback="")),
        classifier_path_prefixes=_tokens(
            parser.get(section, "classifier_path_prefixes", fallback="")
        ),
        classifier_path_suffix=parser.get(
            section, "classifier_path_suffix", fallback=""
        ).strip()
        or None,
        classifier_class_base_names=_tokens(
            parser.get(section, "classifier_class_base_names", fallback="")
        ),
        classifier_fallback=parser.getboolean(
            section, "classifier_fallback", fallback=False
        ),
        subprocess_paths=_tokens(parser.get(section, "subprocess_paths", fallback="")),
        subprocess_nodeids=_tokens(
            parser.get(section, "subprocess_nodeids", fallback="")
        ),
        subprocess_ignore=_tokens(
            parser.get(section, "subprocess_ignore", fallback="")
        ),
        subprocess_ignore_other_lanes=parser.getboolean(
            section, "subprocess_ignore_other_lanes", fallback=False
        ),
        subprocess_env_set=env_set_pairs,
    )


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token for token in text.split() if token)


def _parse_env_set(text: str) -> Iterable[tuple[str, str]]:
    for token in text.split():
        if "=" not in token:
            raise LaneConfigError(
                f"subprocess_env_set entry '{token}' must be in KEY=VALUE form."
            )
        key, _, value = token.partition("=")
        yield key, value


def _validate_ignore_other_lanes_uniqueness(lanes: tuple[LaneSpec, ...]) -> None:
    lanes_with_flag = [
        spec.name for spec in lanes if spec.subprocess_ignore_other_lanes
    ]
    if len(lanes_with_flag) > 1:
        raise LaneConfigError(
            "At most one lane may set subprocess_ignore_other_lanes=true; "
            f"found: {', '.join(lanes_with_flag)}."
        )


def _validate_subprocess_order_names(
    order: tuple[str, ...],
    lane_names: tuple[str, ...],
    field_name: str,
) -> None:
    known = set(lane_names)
    for name in order:
        if name not in known:
            raise LaneConfigError(
                f"{field_name} references unknown lane '{name}'. Known lanes: {', '.join(lane_names)}."
            )
