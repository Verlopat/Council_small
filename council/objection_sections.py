"""Exclusive, evidence-labelled presentation buckets for Council objections.

The raw reviewer/auditor records are never altered. A quote match is only
textual provenance, not mathematical entailment or a formal proof.
"""
from __future__ import annotations
from council.vrf_audit import (classify_objections, partition_addressed_objections,
                               deduplicate_objections)


def presentation_sections(question: str, objections: list[dict],
                          withheld: list[dict], grounded: dict[str,dict],
                          *, require_grounded: bool) -> dict[str,list[dict]]:
    """Each objection ID appears at most once, in priority order.

    Strict VRF-definition mode never reclassifies grounded-valid criticism
    via regex. Unjudged criticisms are visible separately and cannot be used
    to change the answer. For other research questions, preserve existing
    heuristic classification.
    """
    buckets={"withheld":[],"addressed":[],"conflicts":[],
             "open":[],"unjudged":[],"out_of_scope":[]}
    seen=set()
    for entry in withheld:
        oid=str(entry.get("id") or "")
        if oid and oid not in seen:
            buckets["withheld"].append(dict(entry))
            seen.add(oid)
    remaining=[row for row in objections if row.get("id") not in seen]
    if require_grounded:
        for row in remaining:
            oid=str(row.get("id") or "")
            if not oid or oid in seen:
                continue
            seen.add(oid)
            decision=grounded.get(oid,{})
            base={k:v for k,v in row.items()
                  if k not in {"target_text","target_statement"}}
            if decision.get("grounded"):
                verdict=decision.get("verdict")
                if verdict=="valid":
                    base["advisory_status"]="grounded_valid"
                    base["reference_quote"]=decision.get("quote","")
                    buckets["open"].append(base)
                elif verdict=="already_in_claim":
                    base["matched_requirement"]="exact_claim_quote_grounded"
                    base["reference_quote"]=decision.get("quote","")
                    buckets["addressed"].append(base)
                elif verdict=="contradicts_reference":
                    base["vrf_warnings"]=["grounded_contradicts_reference"]
                    base["reference_quote"]=decision.get("quote","")
                    buckets["conflicts"].append(base)
                elif verdict=="out_of_scope":
                    base["reference_quote"]=decision.get("quote","")
                    buckets["out_of_scope"].append(base)
                else:
                    base["advisory_status"]="unjudged"
                    buckets["unjudged"].append(base)
            else:
                base["advisory_status"]="unjudged"
                buckets["unjudged"].append(base)
    else:
        flagged,unclassified=classify_objections(question,remaining)
        addressed,opened=partition_addressed_objections(unclassified)
        for name,items in (("addressed",addressed),("conflicts",flagged),
                           ("open",opened)):
            for row in items:
                oid=str(row.get("id") or "")
                if not oid or oid in seen:
                    continue
                seen.add(oid)
                buckets[name].append({
                    k:v for k,v in row.items()
                    if k not in {"target_text","target_statement"}})
    for name in buckets:
        if name not in {"withheld","unjudged"}:
            buckets[name]=deduplicate_objections(buckets[name])
    return buckets
