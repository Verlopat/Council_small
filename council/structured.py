"""Provider-specific structured-output hints, never verification evidence.

Groq GPT-OSS supports JSON Schema requests. Gemini's generateContent API
supports responseMimeType and responseSchema under generationConfig.
Local schema and evidence checks always remain authoritative.
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
        "sentence_ids": {"type": "array", "items": {"type": "integer"}},
        "assumptions": STRING_LIST,
        "limitations": STRING_LIST,
        "depends_on": STRING_LIST,
        "dependency_argument": STRINGS,
    },
    "required": [
        "id", "statement", "source_span", "sentence_ids", "assumptions",
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

# Gemini's generateContent schema uses OpenAPI-style type names; make
# optional text fields genuinely optional instead of requiring model-authored
# nulls. The local Pydantic judge contract still rejects invalid content.
GEMINI_JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "status": {"type": "STRING", "enum": ["answer", "unresolved"]},
        "answer": {"type": "STRING"},
        "partial_answer": {"type": "STRING"},
        "blocking": {"type": "ARRAY", "items": {"type": "STRING"}},
        "basis": {"type": "ARRAY", "items": {"type": "STRING"}},
    },
    "required": ["status"],
    "propertyOrdering": [
        "status", "answer", "partial_answer", "blocking", "basis"
    ],
}

def response_format(provider: str, model: str, role: str) -> dict | None:
    if provider == "Gemini":
        if role == "judge":
            return {"type": "gemini_response_schema",
                    "schema": GEMINI_JUDGE_SCHEMA}
        return None
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
