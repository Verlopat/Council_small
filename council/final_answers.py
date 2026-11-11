"""Explicit final-answer extraction and conservative verification.

Formatting is NOT correctness. A claim is independently verified only with
current, aligned, independently checked passing evidence.
"""
from __future__ import annotations
import re
from council.models import ClaimStatus

NUM=r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
SCALAR=rf"(?:{NUM}|yes|no|true|false)"
FINAL_INLINE=re.compile(
    r"\bfinal\s+answer\s*[:=]\s*(?:\*\*)?\s*("+SCALAR+r")\b",re.I)
FINAL=re.compile(
    r"(?:the\s+)?(?:final\s+)?(?:answer|result)\s*(?::|is|=)\s*\**("+NUM+
    r")\**\s*[.!]?\s*$",re.I)
BOX=re.compile(r"\\boxed\{\s*("+NUM+r")\s*\}\s*$")
EQUAL=re.compile(r"=\s*("+NUM+r")\s*$")
LABEL=re.compile(
    r"(?i)(?:(?:the\s+)?(?:final\s+)?answer\s*(?::|is|=)\s*)?"
    r"(?:yes|no|true|false)[.!]?")


def normalize_answer(value:object)->str|None:
    """Validate a single scalar; never infer numbers from arbitrary prose."""
    if not isinstance(value,str):
        return None
    item=value.strip().strip(chr(96)).strip().replace("**","")
    item=item.strip().strip('"').strip("'").strip()
    if re.fullmatch(NUM,item):
        return item.replace(",","")
    if re.fullmatch(r"(?i)(?:yes|no|true|false)",item):
        return item.casefold()
    return None


def extract_final_answer(value:object)->str|None:
    """Prefer the last explicit Final answer label anywhere in the text."""
    if not isinstance(value,str) or not value.strip():
        return None
    labeled=FINAL_INLINE.findall(value)
    if labeled:
        return normalize_answer(labeled[-1])
    for raw in reversed(value.strip().splitlines()):
        item=raw.strip().strip(chr(96)).replace("**","").strip()
        item=re.sub(r"^\[(?:S|R)\d+\]\s*","",item)
        if not item:
            continue
        for pattern in (BOX,FINAL):
            found=pattern.search(item)
            if found:
                return normalize_answer(found.group(1))
        direct=normalize_answer(item)
        if direct is not None:
            return direct
        if re.fullmatch(r"[\d\s+\-*/()%.,^eE]+=\s*"+NUM+r"\s*",item):
            return normalize_answer(EQUAL.search(item).group(1))
        if LABEL.fullmatch(item):
            match=re.search(r"(true|false|yes|no)[.!]?$",item,re.I)
            return normalize_answer(match.group(1)) if match else None
        return None
    return None


def _answer_claim_supported(proposal:dict,ledger,candidate:str)->bool:
    answer_id=proposal.get("answer_claim_id")
    if proposal.get("author_inconsistency"):
        return False
    if not isinstance(answer_id,str) or answer_id not in ledger.claims:
        return False
    if answer_id!=proposal.get("id","")+":answer":
        return False
    claim=ledger.claims[answer_id]
    if (proposal.get("family") is not None
            and claim.owner_family!=proposal.get("family")):
        return False
    # Supported evidence must be about THIS scalar, not an unrelated
    # expression attached to an answer-shaped claim.
    match=re.fullmatch(r"\s*[^=]+\s*=\s*("+NUM+r")\s*",claim.statement)
    if match:
        stated=normalize_answer(match.group(1))
    elif claim.statement.startswith("Reported final scalar result: "):
        stated=normalize_answer(
            claim.statement.removeprefix("Reported final scalar result: "))
    else:
        return False
    if stated is None or stated!=candidate:
        return False
    if claim.status is not ClaimStatus.SUPPORTED or claim.needs_re_evaluation:
        return False
    if not any(
            (ev:=ledger.evidence.get(eid)) is not None
            and ev.claim_version==claim.version and ev.outcome=="pass"
            and ev.independently_checked
            for eid in claim.evidence_ids):
        return False
    return all(ledger.claims[cid].status is not ClaimStatus.CONTRADICTED
               for cid in proposal.get("claim_ids",[]) if cid in ledger.claims)


def proposal_answers(proposals:list[dict],ledger)->tuple[str|None,dict[str,str|None]]:
    candidates={}
    verified=None
    for proposal in proposals:
        candidate=(normalize_answer(proposal.get("final_answer"))
                   or extract_final_answer(
                       proposal.get("answer") or proposal.get("approach")))
        candidates[proposal["id"]]=candidate
        if verified is not None or candidate is None:
            continue
        if select_candidate_answer({proposal["id"]:candidate},
                ledger.claims.values(),ledger.evidence.values(),[proposal])["answer"] is None:
            continue
        if proposal.get("answer_claim_id"):
            # Scoped answer check can pass even with unverified explanatory
            # siblings, but never with a contradicted sibling.
            if _answer_claim_supported(proposal,ledger,candidate):
                verified=candidate
            continue
        # Backward-compatible whole-proposal path for old replay records.
        ids=[cid for cid in proposal.get("claim_ids",[]) if cid in ledger.claims]
        if (ids and len(ids)==len(proposal.get("claim_ids",[]))
                and all(ledger.claims[cid].status is ClaimStatus.SUPPORTED
                        and not ledger.claims[cid].needs_re_evaluation
                        for cid in ids)):
            verified=candidate
    return verified,candidates


def select_candidate_answer(candidates:dict, claims, evidence, proposals=()):
    """Select without hidden gold; scoped passes are preferences, not proof.

    Raw candidates remain available for diagnostics/oracle upper bounds.
    Current contradictions and author inconsistencies must never win fallback.
    """
    from dataclasses import asdict, is_dataclass
    def record(item):
        return asdict(item) if is_dataclass(item) else item
    claim_rows=[record(c) for c in claims]
    evidence_rows=[record(e) for e in evidence]
    owners={p['id']:p for p in proposals}
    eligible=[]
    excluded={}
    for pid, candidate in candidates.items():
        if candidate is None:
            continue
        proposal=owners.get(pid,{})
        owned=[c for c in claim_rows if c['id'].startswith(pid+':')]
        if proposal.get('author_inconsistency'):
            excluded[pid]='author_answer_inconsistent'
            continue
        if any(c.get('status') in {ClaimStatus.CONTRADICTED,ClaimStatus.WITHDRAWN}
               for c in owned):
            excluded[pid]='contradicted_or_withdrawn_claim'
            continue
        answer=next((c for c in owned if c['id']==pid+':answer'),None)
        checks=[e for e in evidence_rows if answer is not None
                and e.get('claim_id')==answer['id']
                and e.get('claim_version')==answer['version']
                and e.get('kind') in {'test','formal_proof'}
                and not str(e.get('checker_kind') or '').startswith('author_')]
        if any(e.get('outcome')=='fail' and e.get('independently_checked')
               for e in checks):
            excluded[pid]='independently_failed_answer_check'
            continue
        # An unaligned pass can guide an explicitly unverified choice, but
        # never overrides a failure or upgrades the answer to verified.
        rank=(-1 if any(e.get('outcome')=='fail' for e in checks) else
              1 if any(e.get('outcome')=='pass' for e in checks) else 0)
        eligible.append((rank,pid,candidate))
    if not eligible:
        return {'answer':None,'proposal_id':None,'basis':'no_eligible_candidate',
                'excluded':excluded}
    rank,pid,answer=max(eligible,key=lambda item:item[0])
    return {'answer':answer,'proposal_id':pid,
            'basis':('scoped_answer_check_pass_unverified' if rank>0 else
                     'unaligned_answer_check_failed_unverified' if rank<0 else
                     'first_eligible_unverified_candidate'),
            'excluded':excluded}
