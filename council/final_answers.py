"""Conservative final-answer extraction and evidence-gated selection.

Formatting extraction is not correctness checking. A result is verified only
when all claims from that proposal have independent, current support.
"""
from __future__ import annotations
import re
from council.models import ClaimStatus

NUM=r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?"
FINAL=re.compile(r"(?:the\s+)?(?:final\s+)?(?:answer|result)\s*(?::|is|=)\s*\**("+NUM+r")\**\s*[.!]?\s*$",re.I)
BOX=re.compile(r"\\boxed\{\s*("+NUM+r")\s*\}\s*$")
EQUAL=re.compile(r"=\s*("+NUM+r")\s*$")


def extract_final_answer(value: object) -> str | None:
    """Only explicit terminal numeric/boolean answers; never arbitrary numbers."""
    if not isinstance(value,str) or not value.strip():
        return None
    for raw in reversed(value.strip().splitlines()):
        item=raw.strip().strip(chr(96)).replace("**","").strip()
        item=re.sub(r"^\[(?:S|R)\d+\]\s*","",item)
        if not item:
            continue
        for pattern in (BOX,FINAL):
            found=pattern.search(item)
            if found:
                return found.group(1).replace(",","")
        if re.fullmatch(NUM,item):
            return item.replace(",","")
        # Equation ends in a number; do not parse a number in prose.
        if re.fullmatch(r"[\d\s+\-*/()%.,^]+=\s*"+NUM+r"\s*",item):
            return EQUAL.search(item).group(1).replace(",","")
        if re.fullmatch(r"(?i)(?:final\s+answer\s*:\s*)?(?:true|false|yes|no)",item):
            return re.search(r"(true|false|yes|no)$",item,re.I).group(1).lower()
        return None
    return None


def proposal_answers(proposals:list[dict],ledger) -> tuple[str|None,dict[str,str|None]]:
    candidates={}
    verified=None
    for proposal in proposals:
        candidate=extract_final_answer(
            proposal.get("answer") or proposal.get("approach"))
        candidates[proposal["id"]]=candidate
        ids=[cid for cid in proposal.get("claim_ids",[])
             if cid in ledger.claims]
        if (verified is None and candidate is not None and ids and
                len(ids)==len(proposal.get("claim_ids",[])) and
                all(ledger.claims[cid].status is ClaimStatus.SUPPORTED
                    and not ledger.claims[cid].needs_re_evaluation
                    for cid in ids)):
            verified=candidate
    return verified,candidates
