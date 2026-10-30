"""Present proof obligations once per claim without concealing distinct blockers.

No theorem is marked verified by this display operation. Every source item
remains represented in the resulting combined human-readable description.
"""
from __future__ import annotations


def group_by_claim_id(items: list[str], claim_ids) -> list[str]:
    ids = sorted((c for c in claim_ids if isinstance(c, str)),
                 key=len, reverse=True)
    grouped: dict[str, list[str]] = {}
    for raw in items:
        item = str(raw).strip()
        if not item:
            continue
        claim_id = next((cid for cid in ids
                         if item.startswith(cid + ":")
                         or item.endswith(" " + cid)), None)
        if claim_id is None:
            grouped.setdefault(item, [])
            continue
        detail = (item[len(claim_id) + 1:].strip()
                  if item.startswith(claim_id + ":")
                  else item[:-(len(claim_id))].strip())
        # These two messages are the same missing-provenance obligation.
        if ("provide an exact quote from the original proposal" in detail
                or "exact source span for" in detail):
            detail = "exact source anchor missing"
        if detail:
            notes = grouped.setdefault(claim_id, [])
            if detail not in notes:
                notes.append(detail)
    return [
        (key + ": " + "; ".join(notes)) if notes else key
        for key, notes in grouped.items()
    ]
