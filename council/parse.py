"""Parse untrusted model JSON without executing content or fabricating missing data."""
from __future__ import annotations
import json
import re
from typing import Any

class OutputError(ValueError):
    pass

def parse_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise OutputError("Empty model output")
    raw = text.strip()
    decoder = json.JSONDecoder()
    # Prefer explicit fenced JSON, then a left-aligned outer object. Braces
    # inside prose, math sets, and LaTeX must not shadow the intended reply.
    # Never scan arbitrary indented/nested positions in truncated JSON.
    positions = [m.start(1) for m in re.finditer(
        r"```(?:json)?\\s*\\n?\\s*(\\{)", raw, re.I)]
    positions += [m.start() for m in re.finditer(r"(?m)^\\{", raw)]
    first = raw.find("{")
    if first >= 0:
        positions.append(first)
    if not positions:
        raise OutputError("No JSON object in model output")
    seen = set()
    last_error = None
    for pos in positions:
        if pos in seen:
            continue
        seen.add(pos)
        try:
            value, end = decoder.raw_decode(raw[pos:])
        except (ValueError, TypeError) as exc:
            last_error = exc
            continue
        if not isinstance(value, dict):
            continue
        remainder = raw[pos + end:].strip()
        if remainder.startswith(("{", "[")):
            raise OutputError("Multiple JSON values in model output")
        return value
    raise OutputError("Incomplete or invalid outer JSON object") from last_error

def require_string(obj: dict, name: str) -> str:
    value = obj.get(name)
    if not isinstance(value, str) or not value.strip():
        raise OutputError("Missing nonempty string: " + name)
    return value.strip()

def string_list(obj: dict, name: str) -> list[str]:
    value = obj.get(name, [])
    if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
        raise OutputError("Invalid list: " + name)
    return [s.strip() for s in value if s.strip()]

def item_list(obj: dict, name: str) -> list[dict]:
    value = obj.get(name, [])
    if not isinstance(value, list) or any(not isinstance(x, dict) for x in value):
        raise OutputError("Invalid records: " + name)
    return value
