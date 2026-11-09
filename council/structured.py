"""Provider-specific structured-output hints, never verification evidence.

Groq GPT-OSS supports JSON Schema requests. Gemini's generateContent API
supports responseMimeType and responseSchema under generationConfig.
Local schema and evidence checks always remain authoritative.
"""
from __future__ import annotations
import os

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
        "artifact": {"type":"object","additionalProperties":True},
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

# Gemini's topic judge needs a compact, explicit nested contract.
# Topic and summary are optional because the caller already knows both
# and the judge may return only version assessments.
GEMINI_TOPIC_JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "topic": {"type": "STRING"},
        "summary": {"type": "STRING"},
        "versions": {"type": "ARRAY", "items": {
            "type": "OBJECT", "properties": {
                "id": {"type": "STRING"},
                "status": {"type": "STRING",
                           "enum": ["matches", "contradicts", "incomplete"]},
                "reference_quote": {"type": "STRING"},
                "reason": {"type": "STRING"}},
            "required": ["id", "status", "reason"],
            "propertyOrdering": ["id", "status", "reference_quote", "reason"]}},
        "best_version_id": {"type": "STRING", "nullable": True},
        "missing": {"type": "ARRAY", "items": {"type": "STRING"}},
        "partial_matches": {"type": "ARRAY", "items": {
            "type": "OBJECT", "properties": {
                "id": {"type": "STRING"},
                "agrees": {"type": "ARRAY", "items": {"type": "STRING"}},
                "conflicts": {"type": "ARRAY", "items": {"type": "STRING"}},
                "reference_quote": {"type": "STRING"}},
            "required": ["id"],
            "propertyOrdering": ["id", "agrees", "conflicts", "reference_quote"]}},
    },
    "required": ["versions"],
    "propertyOrdering": ["topic", "versions", "best_version_id",
                         "missing", "partial_matches", "summary"],
}


GEMINI_OBJECTION_JUDGE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "items": {"type": "ARRAY", "items": {
            "type": "OBJECT", "properties": {
                "id": {"type": "STRING"},
                "verdict": {"type": "STRING", "enum": [
                    "valid", "contradicts_reference",
                    "already_in_claim", "out_of_scope"]},
                "quote": {"type": "STRING"},
                "reason": {"type": "STRING"}},
            "required": ["id", "verdict", "quote"],
            "propertyOrdering": ["id", "verdict", "quote", "reason"]}},
    },
    "required": ["items"],
    "propertyOrdering": ["items"],
}


def response_format(provider: str, model: str, role: str) -> dict | None:
    if provider == "Cohere":
        # Chat v2: response_format={type:json_object,schema:...}
        # Never interpret provider-side schema compliance as source verification.
        if role == "proposal":
            return {"type": "cohere_json", "schema": PROPOSAL_SCHEMA}
        return {"type": "cohere_json"}
    if provider == "Gemini":
        if role == "judge":
            # Diagnostic escape hatch: helps distinguish schema-triggered
            # 5xx errors from provider-side outages. Local validation remains.
            if os.getenv("COUNCIL_GEMINI_JUDGE_SCHEMA", "1") == "0":
                return None
            return {"type": "gemini_response_schema",
                    "schema": GEMINI_JUDGE_SCHEMA}
        if role == "topic_judge":
            if os.getenv("COUNCIL_GEMINI_TOPIC_JUDGE_SCHEMA", "1") == "0":
                return None
            return {"type": "gemini_response_schema",
                    "schema": GEMINI_TOPIC_JUDGE_SCHEMA}
        if role == "objection_judge":
            if os.getenv("COUNCIL_GEMINI_OBJECTION_JUDGE_SCHEMA", "1") == "0":
                return None
            return {"type": "gemini_response_schema",
                    "schema": GEMINI_OBJECTION_JUDGE_SCHEMA}
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
