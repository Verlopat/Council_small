"""Conservative definition routing to locally indexed reference provenance.

Never convert a matched heading or source quote into verification of a claim.
"""
from __future__ import annotations
import re
import unicodedata

# Normalize *only* label formatting, not mathematical semantics. The
# model often writes "full‑uniqueness" (nonbreaking hyphen) instead of
# "full uniqueness", causing an expensive fallthrough to the translator.
_TOPIC_DASHES = str.maketrans({ch: " " for ch in
    "\u2010\u2011\u2012\u2013\u2014\u2212-"})


def topic_text(value: str) -> str:
    if not isinstance(value, str):
        return ""
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.translate(_TOPIC_DASHES).casefold().split())


# Prefer the specific trusted-key definition when a claim contrasts
# trusted uniqueness with full uniqueness in the same sentence.
DEFINITIONS = (
    ("trusted uniqueness", "Trusted Uniqueness", "3.3"),
    ("full uniqueness", "Full Uniqueness", "3.1"),
    ("pseudorandomness", "Full Pseudorandomness", "3.4"),
)

SECTION_HEADINGS = {section: heading for _, heading, section in DEFINITIONS}


def is_vrf_definition_question(question: str) -> bool:
    """True only for VRF game/definition explanations, not proofs of security."""
    q=topic_text(question)
    return bool(re.search(r"\bvrfs?\b|verifiable random functions?",q)
                and re.search(r"\b(?:explain|define|describe|compare|what\s+are|what\s+is)\b",q)
                and (re.search(r"\b(?:security\s+)?games?\b|\bdefinitions?\b",q)
                     or re.search(r"\bfull uniqueness\b|\btrusted uniqueness\b|"
                                  r"\bpseudorandomness\b",q))
                and not re.search(r"\b(?:prove|proof\s+of\s+security|"
                                  r"security\s+reduction|implement|construct|"
                                  r"build\s+a\s+vrf|benchmark)\b",q))


def game_step(question: str, statement: str) -> bool:
    """Identify generic VRF game steps lacking explicit property names.

    These are definitional context, NOT candidate theorems to send to a
    translator. A missing game label must not be guessed as a particular
    RFC subsection.
    """
    question_norm=topic_text(question)
    if not re.search(r"\bvrfs?\b|verifiable random functions?",question_norm):
        return False
    if not re.search(r"\b(?:security\s+)?games?\b|\buniqueness\b|\bpseudorandom",question_norm):
        return False
    text=topic_text(statement)
    if re.search(r"\breduc(?:es?|tion)\b|\bproof of\b|\bunder (?:lwe|sis)\b|"
                 r"\b(?:this|our|the proposed) (?:scheme|construction|vrf)\b|"
                 r"\b(?:satisfies|achieves|is secure|holds assuming|follows from)\b",text):
        return False
    return bool(re.search(r"\bchalleng(?:e|er)\b|\badversar(?:y|ial)\b|"
                          r"\boracle\b|\bgames?\b|\bwins?\b",text))



def classify(question: str, statement: str) -> tuple[str, str] | None:
    if not re.search(r"\bvrfs?\b|verifiable random functions?", question, re.I):
        return None
    text = topic_text(statement)
    # Do not skip genuine construction, formal reduction, empirical claim,
    # or theorem assertion. This route locates source *definitions* only.
    if re.search(r"\breduc(?:es?|tion)\b|\bproof of\b|\bunder (?:lwe|sis)\b|"
                 r"\b(?:this|our|the proposed) (?:scheme|construction|vrf)\b|"
                 r"\b(?:satisfies|achieves|is secure|holds assuming|follows from)\b",
                 text):
        return None
    # A definition can be expressed as a declarative requirement without
    # literally saying 'game': 'Full uniqueness requires that...'.
    definitional = re.search(
        r"\bgame\b|\bdefinition\b|\bdefines?\b|\brequires?\b|"
        r"\buses?\b|\bunlike\b|\bdiffers?\b|\bcontrasts?\b|"
        r"\bassumes?\b|\bensures?\b|\bmeans?\b|\bproperty\b|"
        r"\b(?:cannot|must not|infeasible|adversary)\b", text)
    if not definitional:
        return None
    for label, heading, section in DEFINITIONS:
        if label in text:
            return heading, section
    return None


def is_summary(statement: str) -> bool:
    text = topic_text(statement)
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
