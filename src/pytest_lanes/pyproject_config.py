"""Lane configuration loader for ``pyproject.toml``."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:  # pragma: no cover - selected by interpreter version, not by the suite
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 has no tomllib
    import tomli as tomllib  # type: ignore[no-redef]

from pytest_lanes.config import (
    DEFAULT_SHARD_MIN_SAVING_SECONDS,
    LaneConfig,
    LaneConfigError,
    LaneSpec,
    parse_divisible_value,
    validate_ignore_other_lanes_uniqueness,
    validate_positive_lane_numprocesses,
    validate_subprocess_order_names,
)

TOOL_TABLE_PATH = "tool.pytest-lanes"
LANE_TABLE_KEY = "lane"
INI_OPTIONS_TABLE_PATH = "tool.pytest.ini_options"

_MARKERS_FIELD = f"[{INI_OPTIONS_TABLE_PATH}].markers"

# Unknown keys are refused; a misspelled option is a typo, not an extension.
_INDEX_KEYS: tuple[str, ...] = (
    "lanes",
    "subprocess_order_standard",
    "subprocess_order_full",
    "max_workers",
    "shard_min_saving",
    LANE_TABLE_KEY,
)
_LANE_KEYS: tuple[str, ...] = (
    "marker",
    "classifier_paths",
    "classifier_path_prefixes",
    "classifier_path_suffix",
    "classifier_class_base_names",
    "classifier_fallback",
    "subprocess_paths",
    "subprocess_nodeids",
    "subprocess_ignore",
    "subprocess_ignore_other_lanes",
    "subprocess_env_set",
    "tolerate_no_tests",
    "lane_numprocesses",
    "divisible",
)


def load_lane_config_from_pyproject(pyproject_path: Path) -> LaneConfig:
    """Load lane config from the ``[tool.pytest-lanes]`` table of a pyproject."""
    document = _read_toml(pyproject_path)
    lanes_table = _lanes_table_or_none(document)
    if lanes_table is None:
        raise LaneConfigError(
            f"No [{TOOL_TABLE_PATH}] table in {pyproject_path}; "
            "the plugin requires lane configuration."
        )
    return _lane_config_from(lanes_table, _declared_markers(document))


def load_lane_config_from_pyproject_or_none(pyproject_path: Path) -> LaneConfig | None:
    """Load lane config from a pyproject only if it opts into the plugin."""
    if not pyproject_path.exists():
        return None
    if _lanes_table_or_none(_read_toml(pyproject_path)) is None:
        return None
    return load_lane_config_from_pyproject(pyproject_path)


def _lane_config_from(
    lanes_table: dict[str, Any], declared_markers: set[str]
) -> LaneConfig:
    _reject_unknown_keys(lanes_table, _INDEX_KEYS, f"[{TOOL_TABLE_PATH}]")

    index = _index_fields(lanes_table)
    lane_names = index.required_string_array("lanes")
    if not lane_names:
        raise LaneConfigError(
            f"[{TOOL_TABLE_PATH}].lanes must declare at least one lane."
        )

    lane_tables = _lane_tables(lanes_table)
    _reject_undeclared_lane_tables(lane_tables, lane_names)
    lanes = tuple(
        _parse_lane(lane_tables, name, declared_markers) for name in lane_names
    )
    validate_ignore_other_lanes_uniqueness(lanes)

    subprocess_order_standard = index.optional_string_array("subprocess_order_standard")
    subprocess_order_full = index.optional_string_array("subprocess_order_full")
    validate_subprocess_order_names(
        subprocess_order_standard, lane_names, "subprocess_order_standard"
    )
    validate_subprocess_order_names(
        subprocess_order_full, lane_names, "subprocess_order_full"
    )

    return LaneConfig(
        lanes=lanes,
        subprocess_order_standard=subprocess_order_standard,
        subprocess_order_full=subprocess_order_full,
        max_workers=index.optional_int("max_workers"),
        shard_min_saving=index.optional_number(
            "shard_min_saving", DEFAULT_SHARD_MIN_SAVING_SECONDS
        ),
    )


def _parse_lane(
    lane_tables: dict[str, Any], name: str, declared_markers: set[str]
) -> LaneSpec:
    lane_table = _lane_table(lane_tables, name)
    _reject_unknown_keys(lane_table, _LANE_KEYS, f"Lane '{name}'")

    fields = _lane_fields(lane_table, name)
    marker = fields.optional_string("marker")
    if marker is None:
        raise LaneConfigError(f"Lane '{name}' is missing the required 'marker' field.")
    if marker not in declared_markers:
        raise LaneConfigError(
            f"Lane '{name}' uses marker '{marker}' which is not declared in "
            f"{_MARKERS_FIELD}."
        )

    return LaneSpec(
        name=name,
        marker=marker,
        classifier_paths=fields.optional_string_array("classifier_paths"),
        classifier_path_prefixes=fields.optional_string_array(
            "classifier_path_prefixes"
        ),
        classifier_path_suffix=fields.optional_string("classifier_path_suffix"),
        classifier_class_base_names=fields.optional_string_array(
            "classifier_class_base_names"
        ),
        classifier_fallback=fields.optional_bool("classifier_fallback"),
        subprocess_paths=fields.optional_string_array("subprocess_paths"),
        subprocess_nodeids=fields.optional_string_array("subprocess_nodeids"),
        subprocess_ignore=fields.optional_string_array("subprocess_ignore"),
        subprocess_ignore_other_lanes=fields.optional_bool(
            "subprocess_ignore_other_lanes"
        ),
        subprocess_env_set=fields.optional_string_table("subprocess_env_set"),
        tolerate_no_tests=fields.optional_bool("tolerate_no_tests"),
        lane_numprocesses=_lane_numprocesses(fields, name),
        divisible=_divisible(fields, name),
    )


def _lane_numprocesses(fields: _TomlFields, lane_name: str) -> int | None:
    declared = fields.optional_int("lane_numprocesses")
    if declared is None:
        return None
    return validate_positive_lane_numprocesses(declared, lane_name)


def _divisible(fields: _TomlFields, lane_name: str) -> bool:
    declared = fields.optional_string("divisible")
    if declared is None:
        return False
    return parse_divisible_value(declared, lane_name)


def _read_toml(pyproject_path: Path) -> dict[str, Any]:
    try:
        with pyproject_path.open("rb") as stream:
            return tomllib.load(stream)
    except tomllib.TOMLDecodeError as error:
        raise LaneConfigError(f"{pyproject_path} is not valid TOML: {error}") from error


def _lanes_table_or_none(document: dict[str, Any]) -> dict[str, Any] | None:
    return _nested_table_or_none(document, ("tool", "pytest-lanes"))


def _nested_table_or_none(
    document: dict[str, Any], path: tuple[str, ...]
) -> dict[str, Any] | None:
    table: dict[str, Any] = document
    for key in path:
        value = table.get(key)
        if not isinstance(value, dict):
            return None
        table = value
    return table


def _lane_tables(lanes_table: dict[str, Any]) -> dict[str, Any]:
    tables = lanes_table.get(LANE_TABLE_KEY, {})
    if not isinstance(tables, dict):
        raise LaneConfigError(
            f"[{TOOL_TABLE_PATH}].{LANE_TABLE_KEY} must be a table of lane tables "
            f"(got {_describe_type(tables)})."
        )
    return tables


def _lane_table(lane_tables: dict[str, Any], name: str) -> dict[str, Any]:
    lane_table = lane_tables.get(name)
    if lane_table is None:
        raise LaneConfigError(
            f"Lane '{name}' is declared in [{TOOL_TABLE_PATH}].lanes but has no "
            f"[{_lane_table_path(name)}] table."
        )
    if not isinstance(lane_table, dict):
        raise LaneConfigError(
            f"[{_lane_table_path(name)}] must be a table "
            f"(got {_describe_type(lane_table)})."
        )
    return lane_table


def _lane_table_path(name: str) -> str:
    return f"{TOOL_TABLE_PATH}.{LANE_TABLE_KEY}.{name}"


def _reject_unknown_keys(
    table: dict[str, Any], valid_keys: tuple[str, ...], owner: str
) -> None:
    for key in table:
        if key not in valid_keys:
            raise LaneConfigError(
                f"{owner} has unknown key '{key}'. Valid keys: {', '.join(valid_keys)}."
            )


def _reject_undeclared_lane_tables(
    lane_tables: dict[str, Any], lane_names: tuple[str, ...]
) -> None:
    for name in lane_tables:
        if name not in lane_names:
            raise LaneConfigError(
                f"[{_lane_table_path(name)}] defines lane '{name}' which is not "
                f"listed in [{TOOL_TABLE_PATH}].lanes. "
                f"Declared lanes: {', '.join(lane_names)}."
            )


def _declared_markers(document: dict[str, Any]) -> set[str]:
    declared: set[str] = set()
    for entry in _marker_entries(document):
        # pytest marker syntax is "name: description"; allow no description too.
        name = entry.split(":", 1)[0].strip()
        if name:
            declared.add(name)
    return declared


def _marker_entries(document: dict[str, Any]) -> tuple[str, ...]:
    # pytest accepts markers as an array or a newline-separated string.
    ini_options = _nested_table_or_none(document, ("tool", "pytest", "ini_options"))
    markers = (ini_options or {}).get("markers")
    if markers is None:
        return ()
    if isinstance(markers, str):
        return tuple(markers.splitlines())
    if isinstance(markers, list):
        return _string_array(markers, _MARKERS_FIELD)
    raise LaneConfigError(
        f"{_MARKERS_FIELD} must be an array of strings or a newline-separated "
        f"string (got {_describe_type(markers)})."
    )


@dataclass(frozen=True)
class _TomlFields:
    """Typed reader over one TOML table, reporting in the loader's error voice."""

    table: dict[str, Any]
    field_prefix: str

    def required_string_array(self, key: str) -> tuple[str, ...]:
        return _string_array(self.table.get(key, []), self._field(key))

    def optional_string(self, key: str) -> str | None:
        value = self.table.get(key)
        if value is None:
            return None
        return _string(value, self._field(key))

    def optional_string_array(self, key: str) -> tuple[str, ...]:
        value = self.table.get(key)
        if value is None:
            return ()
        return _string_array(value, self._field(key))

    def optional_bool(self, key: str) -> bool:
        value = self.table.get(key)
        if value is None:
            return False
        if not isinstance(value, bool):
            raise LaneConfigError(
                f"{self._field(key)} must be a boolean (got {_describe_type(value)})."
            )
        return value

    def optional_int(self, key: str) -> int | None:
        value = self.table.get(key)
        if value is None:
            return None
        # TOML booleans are Python bools, which are ints; a flag is not a count.
        if isinstance(value, bool) or not isinstance(value, int):
            raise LaneConfigError(
                f"{self._field(key)} must be an integer (got {_describe_type(value)})."
            )
        return value

    def optional_number(self, key: str, default: float) -> float:
        value = self.table.get(key)
        if value is None:
            return default
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise LaneConfigError(
                f"{self._field(key)} must be a number (got {_describe_type(value)})."
            )
        return float(value)

    def optional_string_table(self, key: str) -> tuple[tuple[str, str], ...]:
        value = self.table.get(key)
        if value is None:
            return ()
        field = self._field(key)
        if not isinstance(value, dict):
            raise LaneConfigError(
                f'{field} must be a table of KEY = "value" entries '
                f"(got {_describe_type(value)})."
            )
        for entry_key, entry_value in value.items():
            if not isinstance(entry_value, str):
                raise LaneConfigError(
                    f"{field} values must be strings (got "
                    f"{_describe_type(entry_value)} for '{entry_key}')."
                )
        return tuple(value.items())

    def _field(self, key: str) -> str:
        return f"{self.field_prefix}{key}"


def _index_fields(lanes_table: dict[str, Any]) -> _TomlFields:
    return _TomlFields(table=lanes_table, field_prefix=f"[{TOOL_TABLE_PATH}].")


def _lane_fields(lane_table: dict[str, Any], lane_name: str) -> _TomlFields:
    return _TomlFields(table=lane_table, field_prefix=f"Lane '{lane_name}': ")


def _string_array(value: Any, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise LaneConfigError(
            f"{field} must be an array of strings (got {_describe_type(value)})."
        )
    for entry in value:
        if not isinstance(entry, str):
            raise LaneConfigError(
                f"{field} must contain only strings "
                f"(got {_describe_type(entry)} in the array)."
            )
    return tuple(value)


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise LaneConfigError(
            f"{field} must be a string (got {_describe_type(value)})."
        )
    return value


_TYPE_DESCRIPTIONS = (
    (bool, "a boolean"),
    (int, "an integer"),
    (float, "a float"),
    (str, "a string"),
    (list, "an array"),
    (dict, "a table"),
)


def _describe_type(value: Any) -> str:
    for candidate_type, description in _TYPE_DESCRIPTIONS:
        if isinstance(value, candidate_type):
            return description
    return f"a {type(value).__name__}"
