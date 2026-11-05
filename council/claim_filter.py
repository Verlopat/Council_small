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


def close_to_owner(statement: str, excerpt: str, owner_claims, *,
                   threshold: float = 0.90) -> str | None:
    """Return the existing claim ID for a high-confidence duplicate.

    Exact source-span coverage can be recorded separately from semantic
    equivalence. Does not merge claims or copy evidence between claims.
    """
    normalized=topic_text(statement)
    span=topic_text(excerpt)
    if len(normalized)<20:
        return None
    for claim in owner_claims:
        owner=topic_text(claim.statement)
        source=topic_text(claim.source_span or "")
        score=SequenceMatcher(None,normalized,owner,autojunk=False).ratio()
        if score>=threshold:
            return claim.id
        # A rival's exact sentence is already explicitly cited in the
        # owner's claim provenance. Skip only if the excerpt is substantial.
        if len(span)>=45 and len(source)>=len(span) and span in source:
            return claim.id
    return None
