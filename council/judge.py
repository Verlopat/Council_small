"""Compact, auditable blind judge input; never an evidence validator.

The output explicitly lists every blocker and every claim omitted from the
presentation. A compacted or truncated statement cannot be certified by a
model's prose judgment.
"""
from __future__ import annotations
import json
from collections import defaultdict
from council.definition_sources import topic_text
from council.models import ClaimLedger, ClaimStatus


def topic_of(statement: str) -> str:
    text=topic_text(statement)
    if "trusted uniqueness" in text:
        return "2_trusted_uniqueness"
    if "full uniqueness" in text:
        return "1_full_uniqueness"
    if "pseudorandom" in text:
        return "3_pseudorandomness"
    if "collision resist" in text:
        return "4_collision_resistance"
    return "5_other"


def blind_ledger(ledger: ClaimLedger, *, max_chars: int = 12000,
                 warning_kinds: dict[str,list[str]] | None = None) -> str:
    if max_chars<1000:
        raise ValueError("Blind ledger budget is too small")
    warnings=warning_kinds or {}
    claims=[c for c in ledger.claims.values()
            if not c.id.startswith("composition:") and
            not getattr(c,"duplicate_of",None)]
    blockers=sorted(c.id for c in claims
                    if c.status is not ClaimStatus.SUPPORTED or
                    c.needs_re_evaluation)
    def build(text_limit: int, excluded: set[str]):
        rows=[]
        for c in claims:
            if c.id in excluded:
                continue
            raw=c.statement
            text=raw[:text_limit]
            items=[]
            for ident in c.evidence_ids:
                e=ledger.evidence.get(ident)
                if e:
                    items.append(e.kind.value+":"+e.outcome+
                                 (":independent" if e.independently_checked
                                  else ":unverified"))
            rows.append({"id":c.id,"topic":topic_of(raw),
                         "statement":text,
                         "truncated":len(text)<len(raw),
                         "status":c.status.value,
                         "needs_alignment":bool(c.needs_re_evaluation),
                         "evidence":items[:4],
                         "warning_kinds":list(dict.fromkeys(warnings.get(c.id,[])))[:8]})
        rows.sort(key=lambda r:(r["topic"],r["id"]))
        payload={"all_blocking_claim_ids":blockers,"records":rows,
                 "omitted_claim_ids":sorted(excluded),
                 "presentation_only":True,
                 "verification_policy":"Only independently scoped evidence can support a claim"}
        return json.dumps(payload,ensure_ascii=False,separators=(",",":"))
    excluded=set()
    for limit in (360,280,200,140,90):
        result=build(limit,excluded)
        if len(result)<=max_chars:
            return result
    # A deliberate, recorded omission is safer than a fabricated summary.
    # Never remove claims with advisory findings.
    ordered=sorted((c for c in claims if not warnings.get(c.id)),
                   key=lambda c:(c.status is not ClaimStatus.SUPPORTED,
                                 c.needs_re_evaluation,len(c.statement)))
    for c in ordered:
        excluded.add(c.id)
        result=build(140,excluded)
        if len(result)<=max_chars:
            return result
    raise ValueError("Compact judge input exceeds budget with critical claim warnings")


def _substantive_text(value) -> str | None:
    if not isinstance(value,str):
        return None
    cleaned=value.strip()
    if not cleaned or cleaned.casefold() in {
            "null","none","n/a","undefined","(none)","no answer"}:
        return None
    return cleaned


def enforce_verdict(proposed: dict, ledger: ClaimLedger) -> dict:
    wanted=proposed.get("status")
    if wanted not in {"answer","unresolved"}:
        wanted="unresolved"
    blocking=sorted(c.id for c in ledger.claims.values()
                    if c.status is not ClaimStatus.SUPPORTED or c.needs_re_evaluation)
    if blocking:
        wanted="unresolved"
    explicit=proposed.get("cause")
    hard_causes={"judge_error","composition_failure","deadline",
                 "quota_contention","insufficient_independence",
                 "judge_input_too_large"}
    answer=_substantive_text(proposed.get("answer"))
    partial=_substantive_text(proposed.get("partial_answer")) or answer
    if partial is None and wanted=="unresolved" and explicit is None:
        explicit="judge_error"
    if answer is None and wanted=="answer":
        wanted="unresolved"
        explicit="judge_error"
    cause=(explicit if explicit in hard_causes else
           ("blocking_claims" if blocking else explicit))
    if explicit in hard_causes:
        wanted="unresolved"
    return {"status":wanted,"answer":answer if wanted=="answer" else None,
            "partial_answer":partial,"blocking":blocking,
            "basis":proposed.get("basis",[]),"cause":cause}


def judge_failure(ledger: ClaimLedger, partial: str = "") -> dict:
    return enforce_verdict({"status":"unresolved","answer":None,
                            "partial_answer":partial,"cause":"judge_error"},ledger)

TOPIC_SECTIONS = {
    "full_uniqueness": ("1_full_uniqueness", "3.1"),
    "trusted_uniqueness": ("2_trusted_uniqueness", "3.3"),
    "pseudorandomness": ("3_pseudorandomness", "3.4"),
}


def _flat(text: str) -> str:
    """Normalize RFC line wraps and soft hyphens without changing words."""
    return " ".join(text.replace("\u00ad", "").split()).casefold()


def normalize_topic_judgment(topic: str, reference: dict, versions: list[dict],
                             candidate: dict | None) -> dict:
    """Keep one source-alignment opinion per game; never upgrade evidence.

    Model-supplied quotations must match the indexed excerpt after whitespace
    normalization. Invalid/missing quotations cannot ground a positive comparison.
    """
    valid_ids={v["id"]: v for v in versions}
    excerpt=reference.get("excerpt","") if reference else ""
    source_complete=bool(excerpt and not reference.get("truncated",True))
    flat_excerpt=_flat(excerpt)
    raw_rows=(candidate or {}).get("versions") or []
    reported={r.get("id"):r for r in raw_rows
              if isinstance(r,dict) and r.get("id") in valid_ids}
    rows=[]
    for ident,original in valid_ids.items():
        row=reported.get(ident,{})
        verdict=row.get("status","incomplete")
        quote=row.get("reference_quote","")
        if not isinstance(quote,str):quote=""
        grounded=bool(quote.strip() and _flat(quote) in flat_excerpt)
        if verdict not in {"matches","contradicts","incomplete"}:
            verdict="incomplete"
        if not grounded and verdict in {"matches","contradicts"}:
            verdict="incomplete"
        rows.append({"id":ident,"statement":original["statement"],
                     "status":verdict,"reference_quote":quote if grounded else "",
                     "quote_grounded":grounded,
                     "reason":str(row.get("reason") or
                                 "No independently grounded comparison")[:500],
                     "flags":original.get("flags",[])})
    best=(candidate or {}).get("best_version_id")
    # An incomplete official reference is never enough to select a definitive
    # best version. An unquoted 'match' is downgraded above.
    selected=next((r for r in rows if r["id"]==best),None)
    if not (source_complete and selected and selected["reference_quote"] and
            selected["status"] in {"matches","incomplete"}):
        best=None
    partial=[]
    if source_complete:
        for item in (candidate or {}).get("partial_matches",[]) or []:
            if not isinstance(item,dict) or item.get("id") not in valid_ids:
                continue
            quote=item.get("reference_quote","")
            if not isinstance(quote,str) or not quote.strip() or _flat(quote) not in flat_excerpt:
                continue
            agrees=item.get("agrees") or []
            conflicts=item.get("conflicts") or []
            if not (isinstance(agrees,list) and isinstance(conflicts,list)):
                continue
            partial.append({
                "id":item["id"],"reference_quote":quote,
                "agrees":[x[:350] for x in agrees[:3] if isinstance(x,str)],
                "conflicts":[x[:350] for x in conflicts[:3] if isinstance(x,str)]})
    return {"topic":topic,"section":reference.get("section") if reference else None,
            "source":"model_advisory" if candidate else "unavailable",
            "reference_complete":source_complete,
            "best_version_id":best,
            "best_statement":selected["statement"] if best else None,
            "summary":str((candidate or {}).get("summary") or
                          (selected["statement"] if best else
                           "No source-aligned consolidation available"))[:1200],
            "missing":[str(x)[:300] for x in
                       ((candidate or {}).get("missing") or [])][:8],
            "partial_matches":partial,
            "versions":rows,"verified":False}
