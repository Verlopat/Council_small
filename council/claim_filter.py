"""Conservative filters for redundant and self-referential research claims.

Skipping is a cost/provenance decision, never logical equivalence or proof.
"""
from __future__ import annotations
from difflib import SequenceMatcher
import re
from council.definition_sources import topic_text

META = re.compile(r"^(?:the\s+(?:answer|response|proposal|brief)|"
                  r"this\s+(?:answer|response|proposal|brief))\b", re.I)


def is_meta_claim(statement: str) -> bool:
    return isinstance(statement,str) and bool(META.match(statement.strip()))


def close_to_owner(statement: str, owner_claims, *,
                   threshold: float = 0.90) -> str | None:
    """Identify near-verbatim rival duplicates without inferring equivalence.

    Shared source spans are NOT sufficient: the rival may extract a different
    (even contradictory) assertion from the same sentence. No claims or
    evidence are merged by this advisory pre-filter.
    """
    normalized = topic_text(statement)
    if len(normalized) < 20:
        return None
    # Negation flips are not safe near-duplicates even with high similarity.
    negations = re.compile(r"\b(?:not|no|never|cannot|without|lacks?|forbidden)\b"
                           r"|\bcan['’]t\b", re.I)
    polarity = set(negations.findall(normalized))
    for claim in owner_claims:
        owner = topic_text(claim.statement)
        if polarity != set(negations.findall(owner)):
            continue
        score = SequenceMatcher(None, normalized, owner, autojunk=False).ratio()
        if score >= threshold:
            return claim.id
    return None
