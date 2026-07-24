"""Boolean parsing for YAML config values."""

from __future__ import annotations

TRUE_VALUES = frozenset({"true", "yes", "1", "on"})
FALSE_VALUES = frozenset({"false", "no", "0", "off"})


def parse_bool(value, field_name: str, default: bool | None = None) -> bool:
    if value is None:
        if default is not None:
            return default
        raise ValueError(f"Invalid boolean for {field_name}: (missing)")

    if isinstance(value, bool):
        return value

    normalized = str(value).strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise ValueError(f"Invalid boolean for {field_name}: {value!r}")


def optional_bool(value, field_name: str, default: bool) -> bool:
    if value is None:
        return default
    return parse_bool(value, field_name)
