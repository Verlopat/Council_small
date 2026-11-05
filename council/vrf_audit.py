"""Advisory sanity checks for model-authored VRF audit objections.

Auditor prose is untrusted model output. These warnings never certify an
objection or resolve it, and are separate from verified counterexamples.
"""
from __future__ import annotations
import re
from types import SimpleNamespace
from council.vrf_sanity import scan_vrf_games


def scan_audit_issues(question: str, issues: list[str]) -> list[dict]:
    if not re.search(r"\bVRF\b|verifiable random function",question,re.I):
        return []
    rows=[]
    for index,issue in enumerate(issues,1):
        if not isinstance(issue,str) or not issue.strip():
            continue
        ident=f"audit:{index}"
        text=" ".join(issue.split())
        if ("pseudorandom" in question.lower() and
            re.search(r"\bproof\b",text,re.I) and
            (re.search(
                r"\b(?:challenge|pseudorandomness)\b.{0,140}"
                r"\b(?:must|should|requires?|needs?)\b.{0,65}"
                r"\b(?:reveal|provide|return|disclose)",text,re.I)
             or re.search(
                r"\bnever\s+reveal\w*\b.{0,150}\bproof\b.{0,240}"
                r"\b(?:contradict|invalid|false|wrong|necessary|must)\b",
                text,re.I)
             or re.search(
                r"\bproof\b.{0,100}\bnecessary\b.{0,90}"
                r"\b(?:uniqueness|correctness)\b",text,re.I))):
            rows.append({
                "claim_id":ident,
                "kind":"auditor_challenge_proof_scope_confusion",
                "message":"Audit objection may incorrectly generalize proof "
                          "disclosure from public VRF verification to the "
                          "pseudorandomness challenge. RFC 9381 Section 3.4 "
                          "requires the challenge output WITHOUT its proof; "
                          "ordinary non-challenge evaluations may have proofs. "
                          "Review the objection's scope before accepting it.",
                "reference":"RFC 9381 Section 3.4"})
        # Full uniqueness does not require the adversary to remain
        # ignorant of a secret key. An auditor objection that presumes
        # secret-key secrecy is at best mis-scoped.
        if (re.search(r"\bfull\s+uniqueness\b",text,re.I) and
            re.search(r"\b(?:no restriction|without restriction|may know|"
                      r"even if|knowledge of)\b.{0,120}"
                      r"\b(?:secret key|\bsk\b)\b",text,re.I) and
            re.search(r"\b(?:contradict|wrong|invalid|unsupported|false|"
                      r"without the secret key|should not)\b",text,re.I)):
            rows.append({
                "claim_id":ident,
                "kind":"auditor_full_uniqueness_secret_key_assumption",
                "message":"The objection appears to assume full uniqueness "
                          "requires keeping a secret key unknown. Full "
                          "uniqueness quantifies over adversarially chosen "
                          "public keys; secret-key ignorance is not its "
                          "defining restriction. Assess key origin and "
                          "accepted outputs, not key secrecy alone.",
                "reference":"RFC 9381 Sections 3.1 and 3.3"})
        rows.extend(scan_vrf_games(question,[
            SimpleNamespace(id=ident,statement=issue)]))
    return list({(r["claim_id"],r["kind"]):r for r in rows}.values())
