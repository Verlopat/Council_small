"""Parse untrusted model JSON without executing content or fabricating missing data."""
from __future__ import annotations
import json
from typing import Any

class OutputError(ValueError):
    pass

def parse_object(text: str) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise OutputError("Empty model output")
    raw = text.strip()
    decoder = json.JSONDecoder()
    # A model may surround its JSON with fences/prose. Never eval expressions.
    for pos, char in enumerate(raw):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(raw[pos:])
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict):
            return value
    raise OutputError("No parseable JSON object")

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
