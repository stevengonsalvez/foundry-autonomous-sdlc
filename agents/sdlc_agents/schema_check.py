"""
Validate parsed JSON against the same schema dict that is registered with the agent.

Supports exactly the JSON Schema subset the agent, state and metrics schemas use. An unknown
keyword raises TypeError (a programming error), so a schema change can never be silently
ignored here. Stdlib only.
"""

from __future__ import annotations

import re
from typing import Any

_KEYWORDS = frozenset({
    "type", "properties", "required", "additionalProperties",
    "items", "minItems", "maxItems", "minLength", "maxLength", "enum",
    "minimum", "maximum", "pattern",
})
_TYPE_NAMES = frozenset({"object", "array", "string", "integer", "number", "boolean", "null"})


def _short(value: Any) -> str:
    text = repr(value)
    return text if len(text) <= 60 else text[:57] + "..."


def _is_type(value: Any, name: str) -> bool:
    # bool is a subclass of int in Python but never a JSON number.
    match name:
        case "object":
            return isinstance(value, dict)
        case "array":
            return isinstance(value, list)
        case "string":
            return isinstance(value, str)
        case "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        case "number":
            return isinstance(value, int | float) and not isinstance(value, bool)
        case "boolean":
            return isinstance(value, bool)
        case _:
            return value is None


def _check_type(schema: dict[str, Any], value: Any, where: str) -> None:
    expected = schema.get("type")
    if expected is None:
        return
    names = expected if isinstance(expected, list) else [expected]
    unsupported = [n for n in names if n not in _TYPE_NAMES]
    if unsupported:
        raise TypeError(f"schema at {where} uses unsupported type: {unsupported[0]!r}")
    if not any(_is_type(value, n) for n in names):
        raise ValueError(f"{where}: expected {'|'.join(names)}, got {type(value).__name__}")


def check(schema: dict[str, Any], value: Any, where: str) -> None:
    """Raise ValueError naming `where` (e.g. 'sdlc-triage: labels[0]') on the first violation."""
    unknown = set(schema) - _KEYWORDS
    if unknown:
        raise TypeError(f"schema at {where} uses unsupported keywords: {sorted(unknown)}")

    _check_type(schema, value, where)
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{where}: {_short(value)} not in allowed set")

    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0):
            raise ValueError(f"{where}: shorter than {schema['minLength']} chars")
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ValueError(f"{where}: exceeds {schema['maxLength']} chars")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ValueError(f"{where}: {_short(value)} does not match {schema['pattern']!r}")

    elif isinstance(value, int | float) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ValueError(f"{where}: {value} is below the minimum {schema['minimum']}")
        if "maximum" in schema and value > schema["maximum"]:
            raise ValueError(f"{where}: {value} is above the maximum {schema['maximum']}")

    elif isinstance(value, list):
        lo, hi = schema.get("minItems", 0), schema.get("maxItems")
        if len(value) < lo or (hi is not None and len(value) > hi):
            bounds = f"{lo}-{hi}" if hi is not None else f"at least {lo}"
            raise ValueError(f"{where}: must have {bounds} items, got {len(value)}")
        if "items" in schema:
            for i, item in enumerate(value):
                check(schema["items"], item, f"{where}[{i}]")

    elif isinstance(value, dict):
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise ValueError(f"{where}: unexpected keys: {sorted(extra)}")
        missing = set(schema.get("required", ())) - set(value)
        if missing:
            raise ValueError(f"{where}: missing keys: {sorted(missing)}")
        for key, sub in props.items():
            if key in value:
                check(sub, value[key], f"{where}.{key}")
