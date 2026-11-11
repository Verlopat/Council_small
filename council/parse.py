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
    # Decode ONLY the first outer object, never a nested object from a
    # truncated reply. Invalid/truncated JSON must not produce default votes.
    pos = raw.find("{")
    if pos < 0:
        raise OutputError("No JSON object in model output")
    try:
        value, end = decoder.raw_decode(raw[pos:])
    except (ValueError, TypeError) as exc:
        raise OutputError("Incomplete or invalid outer JSON object") from exc
    if not isinstance(value, dict):
        raise OutputError("The outer JSON value must be an object")
    remainder = raw[pos + end:].strip()
    if remainder.startswith(("{", "[")):
        raise OutputError("Multiple JSON values in model output")
    return value

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
