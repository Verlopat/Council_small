"""Provider-specific formatting hints, never a substitute for local validation.

Groq GPT-OSS 20B/120B supports strict JSON Schema structured outputs.
All fields in the strict schema are required and every object is closed;
semantic anchors and claim/evidence rules are still checked separately.
"""
from __future__ import annotations

STRINGS = {"type": "string"}
STRING_LIST = {"type": "array", "items": {"type": "string"}}
CLAIM = {
    "type": "object",
    "properties": {
        "id": STRINGS,
        "statement": STRINGS,
        "source_span": STRINGS,
        "assumptions": STRING_LIST,
        "limitations": STRING_LIST,
        "depends_on": STRING_LIST,
        "dependency_argument": STRINGS,
    },
    "required": [
        "id", "statement", "source_span", "assumptions",
        "limitations", "depends_on", "dependency_argument"
    ],
    "additionalProperties": False,
}
PROPOSAL_SCHEMA = {
    "type": "object",
    "properties": {
        "approach": STRINGS,
        "claims": {"type": "array", "items": CLAIM},
        "hypotheses": STRING_LIST,
        "experiments": STRING_LIST,
    },
    "required": ["approach", "claims", "hypotheses", "experiments"],
    "additionalProperties": False,
}

def response_format(provider: str, model: str, role: str) -> dict | None:
    if provider != "Groq" or not model.startswith("openai/gpt-oss-"):
        return None
    if role == "proposal":
        return {
            "type": "json_schema",
            "json_schema": {
                "name": "council_proposal",
                "strict": True,
                "schema": PROPOSAL_SCHEMA,
            },
        }
    # JSON object mode improves syntactic reliability for other Council roles,
    # but does NOT guarantee schema shape or semantic validity.
    return {"type": "json_object"}
