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
                r"\b(?:be\s+)?(?:reveal\w*|provid\w*|return\w*|"
                r"disclos\w*|includ\w*)\s+"
                r"(?:(?:a|an|the|its)\s+)?"
                r"(?:(?:valid(?:ating)?|simulated?)\s+)?proof\b",text,re.I)
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
        # Criticisms quote defective games; scanning them as if they were
        # standalone proposed games invents missing-oracle and proof-leak
        # warnings about the *critic*, not about the claim. Keep only
        # auditor-specific direct-assertion warnings here. Every raw issue
        # still receives separate, narrow objection classification below.
    return list({(r["claim_id"],r["kind"]):r for r in rows}.values())


# These patterns flag *possible* faulty reviewer assertions. An objection
# that quotes an error to criticize it should not be automatically suppressed.
def objection_conflicts(question: str, ident: str, issue: str,
                        topic: str = "") -> list[dict]:
    if not re.search(r"\bVRF\b|verifiable random function",question,re.I):
        return []
    if not isinstance(issue,str):
        return []
    t=" ".join(issue.split())
    # Don't misread quoted criticisms such as "the proposal incorrectly
    # assumes no SK" as the reviewer's own definition.
    quotes_error=bool(re.search(
        r"\b(?:incorrectly|wrongly|mistakenly|invalidly|falsely|"
        r"claims?\s+that|assumes?\s+that|error\s+(?:is|in))\b",t,re.I))
    rows=[]
    if ((re.search(r"\btrusted\s+uniqueness\b",t,re.I) or
         topic=="2_trusted_uniqueness") and
        re.search(r"\b(?:without|not\s+(?:given|have|know)|lacks?)\b"
                  r".{0,45}\b(?:SK|secret\s+key)\b",t,re.I)
        and not quotes_error):
        rows.append({"claim_id":ident,"kind":"contradicts_rfc_3_3",
                     "reference":"RFC 9381 Section 3.3",
                     "message":"Objection appears to require target SK secrecy "
                               "in trusted uniqueness; RFC 9381 provides "
                               "the honestly generated secret key to the adversary."})
    pseudo=bool(re.search(r"\bpseudorandom",t,re.I) or
                topic=="3_pseudorandomness")
    # A correct criticism often says "the challenge must be returned without
    # a proof, as verification would trivially distinguish a random value".
    # That is NOT an objection requiring proof disclosure.
    says_must_omit=bool(re.search(
        r"\b(?:must|should|is|are)\s+(?:be\s+)?"
        r"(?:provided|given|returned|revealed|output)\s+without\b"
        r".{0,30}\bproof\b|"
        r"\bwithout\s+(?:a|its|the)\s+proof\b.{0,40}"
        r"\b(?:as|because|since)\b.{0,60}\bverif\w*\b"
        r".{0,60}\b(?:distinguish\w*|trivial\w*)\b",t,re.I))
    # Require an EXPLICIT assertion that the lack of a proof enables an
    # adversary to distinguish; mere co-occurrence is insufficient.
    complains_missing=bool(re.search(
        r"\b(?:no|without|missing|lacks?)\b.{0,40}\bproof\b"
        r".{0,90}\b(?:adversary|it)\b.{0,45}"
        r"\b(?:can|could|would)\b.{0,45}"
        r"\b(?:distinguish\w*|trivial\w*|eas\w*)\b",t,re.I))
    if pseudo and complains_missing and not says_must_omit and not quotes_error:
        rows.append({"claim_id":ident,"kind":"contradicts_rfc_3_4_no_challenge_proof",
                     "reference":"RFC 9381 Section 3.4",
                     "message":"Objection appears to say a missing challenge "
                               "proof makes distinguishing easy. RFC 9381 "
                               "withholds the challenge proof intentionally."})
    return rows


def classify_objections(question: str, objections: list[dict]) -> tuple[list[dict],list[dict]]:
    """Partition advisory RFC conflicts from other objections, preserving raw text.

    No objection is deleted from the audit trail and these heuristics do not
    establish correctness or proof.
    """
    flagged,remaining=[],[]
    for item in objections:
        ident=item.get("id","")
        issue=item.get("issue","")
        # Execute the ordinary VRF sanity pass on every objection as a
        # separate advisory surface; only narrow RFC conflict categories
        # change how the objection is DISPLAYED.
        game_warnings=scan_vrf_games(question,[
            SimpleNamespace(id=ident,statement=issue)])
        conflict=objection_conflicts(question,ident,issue,item.get("topic",""))
        value=dict(item,vrf_warnings=list({
            x["kind"] for x in game_warnings+conflict}))
        (flagged if conflict else remaining).append(value)
    return flagged,remaining

# The scope of an objection matters: pre-challenge freshness is not by itself
# a defense against querying the target *after* the challenge.
PRE_CHALLENGE = re.compile(
    r"\b(?:not|never)\s+previously\s+queried\b|"
    r"\bfresh\s+(?:challenge\s+)?input\b|"
    r"\b(?:not|never)\s+queried\s+before\b", re.I)
POST_CHALLENGE = re.compile(
    r"\b(?:forbid\w*|may\s+not|cannot|must\s+not|"
    r"not\s+allow\w*|disallow\w*|prohibit\w*)\b"
    r".{0,90}\b(?:quer\w*|ask\w*|eval(?:uate|uation)?)\b"
    r".{0,100}(?:x\s*\*|challenge\s+input)|"
    r"\b(?:x\s*\*|challenge\s+input)\b.{0,80}"
    r"\b(?:cannot|must\s+not|forbid\w*|disallow\w*)\b"
    r".{0,50}\bquer\w*\b",re.I)
SK_DISCLOSED = re.compile(
    r"\bgives?\s+(?:both\s+)?pk\s+and\s+sk\b|"
    r"\b(?:adversary|attacker)\s+"
    r"(?:receives|is\s+given|gets|knows)\s+"
    r".{0,45}\b(?:sk|secret\s+key)\b|"
    r"\bgives?\s+(?:the\s+)?adversary\s+"
    r".{0,45}\b(?:sk|secret\s+key)\b",re.I)


def partition_addressed_objections(objections: list[dict]) -> tuple[list[dict],list[dict]]:
    """Advisory: identify complaints answered *in the cited claim's own text*.

    A source quotation is only provenance: lexical coverage never proves
    that the entire game is correct. Raw objections remain in stored records.
    """
    addressed,unresolved=[],[]
    for item in objections:
        issue=str(item.get("issue") or "")
        target=str(item.get("target_text") or "")
        topic=item.get("topic","")
        correction=None
        if topic=="3_pseudorandomness" and re.search(
            r"\b(?:quer\w*|oracle|fresh|challenge\s+input|"
            r"same\s+input)\b",issue,re.I):
            # An objection about later target evaluation needs an explicit
            # prohibition on post-challenge queries, not just past freshness.
            post_issue=bool(re.search(
                r"\b(?:later|after|subsequent|post.challenge)\b|"
                r"\bobtain\w*\s+a\s+proof\b",issue,re.I))
            pre_issue=bool(re.search(
                r"\b(?:fresh|previously|before|already\s+queried)\b",
                issue,re.I))
            if post_issue and POST_CHALLENGE.search(target):
                correction="post_challenge_target_queries_forbidden"
                if pre_issue and not PRE_CHALLENGE.search(target):
                    correction=None
            elif pre_issue and not post_issue and PRE_CHALLENGE.search(target):
                correction="fresh_target_not_previously_queried"
        if not correction and topic=="2_trusted_uniqueness" and re.search(
            r"\b(?:not|never|missing|lacks?|without|only\s+pk)\b"
            r".{0,65}\b(?:sk|secret\s+key)\b",issue,re.I):
            if SK_DISCLOSED.search(target):
                correction="target_secret_key_disclosed"
        clean={k:v for k,v in item.items() if k!="target_text"}
        if correction:
            addressed.append(dict(clean,
                advisory_status="already_addressed_by_claim",
                matched_requirement=correction))
        else:
            unresolved.append(clean)
    return addressed,unresolved
