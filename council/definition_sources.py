"""Conservative definition routing to locally indexed reference provenance.

Never convert a matched heading or source quote into verification of a claim.
"""
from __future__ import annotations
import re

DEFINITIONS = (
    ("full uniqueness", "Full Uniqueness", "3.1"),
    ("trusted uniqueness", "Trusted Uniqueness", "3.3"),
    ("pseudorandomness", "Full Pseudorandomness", "3.4"),
)


def classify(question: str, statement: str) -> tuple[str, str] | None:
    if not re.search(r"\bvrf\b|verifiable random function", question, re.I):
        return None
    text = " ".join(statement.lower().split())
    if not re.search(r"\bgame\b|\bdefinition\b|\bdefines?\b", text):
        return None
    # Do not skip genuine claims about a proof, reduction or implementation.
    if re.search(r"\breduc(?:es?|tion)\b|\bproof of\b|\bunder (?:lwe|sis)\b",
                 text):
        return None
    for label, heading, section in DEFINITIONS:
        if label in text:
            return heading, section
    return None


def is_summary(statement: str) -> bool:
    text = " ".join(statement.strip().lower().split())
    return (text.startswith(("these definitions capture", "in summary,",
                             "overall, these definitions", "taken together,"))
            and sum(bool(term in text) for term in
                    ("uniqueness", "pseudorandomness", "correctness")) >= 2)


def consult(index, heading: str, section: str, claim_id: str) -> dict:
    row = {"claim_id": claim_id, "section": section,
           "source_id": "rfc9381",
           "heading_found": False, "semantic_entailment": "unchecked",
           "meaning": "reference provenance only; no claim verified"}
    if index is None:
        row["reason"] = "No local paper index supplied"
        return row
    # Do not accept a similarly titled arbitrary document as the RFC.
    records = index.retrieve(heading, limit=30)
    if not any(r["id"] == "rfc9381" and
               r.get("source_uri") == "https://www.rfc-editor.org/rfc/rfc9381.txt"
               for r in records):
        row["reason"] = "Official RFC 9381 not found in local index"
        return row
    passage = index.quote("rfc9381", heading)
    row["heading_found"] = passage.found
    row["passage_hash"] = passage.passage_hash
    row["reason"] = ("Reference heading located (not semantic verification)"
                     if passage.found else "Expected heading absent")
    return row
