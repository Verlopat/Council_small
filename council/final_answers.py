"""Explicit final-answer extraction and conservative verification.

Formatting is NOT correctness. A claim is independently verified only with
current, aligned, independently checked passing evidence.
"""
from __future__ import annotations
import re
from fractions import Fraction
from decimal import Decimal
from council.models import ClaimStatus

NUM=r"[+-]?(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?:[eE][+-]?\d+)?"
SCALAR=rf"(?:{NUM}|yes|no|true|false)"
FINAL_INLINE=re.compile(
    r"\bfinal\s+answer\s*[:=]\s*(.*?)(?=\bfinal\s+answer\s*[:=]|$)",re.I|re.M)
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
    item=re.sub(r"(?i)^final\s+answer\s*[:=]\s*", "", item).strip()
    item=item.rstrip("!?").strip()
    # Formatting around an explicit scalar is not part of its value.
    item=re.sub(r"^[$€£]\s*", "", item)
    item=re.sub(r"(?<=\d)\.$", "", item)
    if re.fullmatch(r"(?i)no\s+solutions?(?:\s+exists?)?\.?", item):
        return "no solution"
    if re.fullmatch(NUM, item):
        return item.replace(",","")
    if re.fullmatch(r"(?i)(?:yes|no|true|false)\.?",item):
        return item.rstrip(".").casefold()
    if re.fullmatch(rf"{NUM}\s*/\s*{NUM}", item):
        from fractions import Fraction
        try:
            numerator, denominator = item.split("/", 1)
            value = Fraction(numerator.replace(",", "")) / Fraction(
                denominator.replace(",", ""))
            return str(value.numerator) + "/" + str(value.denominator)
        except (ZeroDivisionError, ValueError):
            return None
    # A number plus one short, nonnumeric unit is still unambiguous.
    # Never treat a second quantity or a modular annotation as a unit.
    unit=re.fullmatch(rf"({NUM})\s*[A-Za-z%°][A-Za-z%° ]{{0,30}}\.?",item)
    if unit:
        return unit.group(1).replace(",", "")
    prefix=re.match(r"(?i)(yes|no|true|false)\s*[,;:]",item)
    if prefix:
        tail=item[prefix.end():].strip()
        # Permit a short explanation after the explicit boolean, but not a
        # contradictory second yes/no or a longer arbitrary answer.
        if (tail and len(tail)<=100
                and not re.search(r"(?i)\b(?:yes|no|true|false)\b",tail)
                and re.fullmatch(r"[A-Za-z][A-Za-z ,;:.'-]*",tail)):
            return prefix.group(1).casefold()
    # Only extract the LAST RHS of a complete, explicit arithmetic equation.
    if "=" in item:
        expression, scalar = item.rsplit("=", 1)
        scalar = scalar.strip().rstrip(".").strip()
        if (re.fullmatch(r"[0-9\s+\-*/().,%^eE]+", expression)
                and re.fullmatch(NUM, scalar)):
            return scalar.replace(",", "")
    return None


def canonical_scalar(value:object)->str|None:
    """Canonicalize an extracted answer exactly (including fractions).

    This is shared by author-code checking and executed-family voting.
    Approximate decimal agreement belongs to the caller, not this function.
    """
    if type(value) is bool:
        return "yes" if value else "no"
    if type(value) not in (str,int,float,Decimal):
        return None
    scalar=normalize_answer(value) if isinstance(value,str) else normalize_answer(str(value))
    if scalar in {"yes","true"}:
        return "yes"
    if scalar in {"no","false"}:
        return "no"
    if scalar=="no solution":
        return scalar
    if scalar is None:
        return None
    try:
        return str(Fraction(scalar))
    except (ValueError,ZeroDivisionError,OverflowError):
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


def executed_answer_selection(proposals,claims,evidence,verified=None):
    """Verified scalar > distinct-family executed agreement > self-consistency.

    Execution is evidence about the submitted code, not its interpretation
    of the question. A corrected printed value never inherits verification
    evidence for the author's different stated answer.
    """
    import hashlib
    from dataclasses import asdict,is_dataclass
    canonical=canonical_scalar
    claim_map={c["id"]:c for c in
               (asdict(c) if is_dataclass(c) else c for c in claims)}
    if verified is not None:
        return {"answer":verified,"proposal_id":next((p['id'] for p in proposals
                if canonical(p.get('final_answer'))==canonical(verified)),None),
                "basis":"independently_verified_answer","families":[]}
    executions=[]
    for p in proposals:
        value=canonical(p.get('executed_answer'))
        code=(p.get('artifact') or {}).get('code')
        claim=claim_map.get(p.get('answer_claim_id'))
        if (value is None or not p.get('family') or not isinstance(code,str)
                or claim is None
                or p.get('executed_claim_version')!=claim.get('version')
                or p.get('executed_artifact_hash')!=hashlib.sha256(code.encode()).hexdigest()):
            continue
        executions.append((p,value))
    per_family={}
    for p,value in executions:
        per_family.setdefault(p['family'],set()).add(value)
    by_value={}
    for family,values in per_family.items():
        if len(values)==1:
            by_value.setdefault(next(iter(values)),set()).add(family)
    agreements=[v for v,families in by_value.items() if len(families)>=2]
    if len(agreements)==1:
        value=agreements[0]
        p=next(p for p,v in executions if v==value and p['family'] in by_value[value])
        return {"answer":value,"proposal_id":p['id'],
                "basis":"executed_agreement_not_formal_proof",
                "families":sorted(by_value[value])}
    if len(agreements)>1:
        return {"answer":None,"proposal_id":None,
                "basis":"conflicting_executed_agreements","families":[]}
    for p,value in executions:
        if (len(per_family[p['family']])==1
                and canonical(p.get('final_answer'))==value):
            # Preserve contradiction gating for the unchanged stated answer.
            choice=select_candidate_answer({p['id']:value},claim_map.values(),evidence,[p])
            if choice['answer'] is not None:
                return {"answer":value,"proposal_id":p['id'],
                        "basis":"self_consistent_execution_unverified",
                        "families":[p['family']]}
    return {"answer":None,"proposal_id":None,
            "basis":"no_verified_or_executed_answer","families":[]}
