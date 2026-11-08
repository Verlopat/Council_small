"""Advisory sanity checks for model-authored VRF audit objections.

Auditor prose is untrusted model output. These warnings never certify an
objection or resolve it, and are separate from verified counterexamples.
"""
from __future__ import annotations
import re
from difflib import SequenceMatcher
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
        # Criticisms quote defective games; scanning them as standalone
        # proposed games creates missing-oracle and proof-leak false positives.
        # Preserve one narrow direct-assertion check for trusted-uniqueness
        # secret-key exclusion, but ignore quoted reports of somebody else's
        # error. All other issues go through objection classification below.
        reports_error=bool(re.search(
            r"\b(?:incorrectly|wrongly|mistakenly|invalidly|falsely|"
            r"claims?\s+that|assumes?\s+that|error\s+(?:is|in))\b",
            text,re.I))
        if not reports_error and re.search(r"\btrusted\s+uniqueness\b",text,re.I):
            direct=scan_vrf_games(question,[
                SimpleNamespace(id=ident,statement=issue)])
            rows.extend(w for w in direct
                        if w["kind"]=="trusted_uniqueness_sk_secrecy_contradiction")
    return list({(r["claim_id"],r["kind"]):r for r in rows}.values())


# These patterns flag *possible* faulty reviewer assertions. An objection
# that quotes an error to criticize it should not be automatically suppressed.
def objection_conflicts(question: str, ident: str, issue: str,
                        topic: str = "") -> list[dict]:
    """Narrow advisory RFC conflicts in objections, not in quoted claims.

    Neither a regex match nor an absence of warnings certifies correctness.
    """
    if not re.search(r"\bVRF\b|verifiable random function",question,re.I):
        return []
    if not isinstance(issue,str):
        return []
    t=" ".join(issue.split())
    trusted=bool(re.search(r"\btrusted\s+uniqueness\b",t,re.I)
                 or topic=="2_trusted_uniqueness")
    pseudo=bool(re.search(r"\bpseudorandom",t,re.I)
                or topic=="3_pseudorandomness")
    # "The claim that ..." reports the claim; it is NOT an admission
    # that the reviewer is quoting an error to criticise it.
    quoted_error=bool(re.search(
        r"\b(?:incorrectly|wrongly|mistakenly|falsely)\s+"
        r"(?:claims?|states?|assumes?)\b|"
        r"\berror\s+(?:is|in)\b",t,re.I))
    notes=[]
    def add(kind,reference,message):
        notes.append({"claim_id":ident,"kind":kind,"reference":reference,
                      "message":message})
    # An objection about an actually missing SK disclosure in the claim
    # is not itself saying the adversary ought to lack the secret key.
    explicitly_reports_error=bool(re.search(
        r"\b(?:yet|however|but)\b.{0,120}"
        r"\b(?:no\s+access|only\s+pk|not\s+given|without|lacks?)\b"
        r".{0,45}\b(?:sk|secret\s+key)\b",t,re.I))
    if trusted and not quoted_error and not explicitly_reports_error:
        if re.search(r"\b(?:without|not\s+(?:given|have|know)|lacks?)\b"
                     r".{0,45}\b(?:sk|secret\s+key)\b",t,re.I):
            add("contradicts_rfc_3_3","RFC 9381 Section 3.3",
                "Objection appears to require secret-key secrecy in trusted "
                "uniqueness; the honestly generated SK is known to the adversary.")
        key_revealed=bool(re.search(
            r"\b(?:secret\s+key|\bsk\b)\b.{0,95}"
            r"\b(?:reveal\w*|known|learn\w*|given|disclos\w*)\b",t,re.I))
        key_condemned=bool(re.search(
            r"\b(?:contradict\w*|trivial\w*|break\w*|insecure|"
            r"violat\w*|undermin\w*|simply)\b|"
            r"\b(?:generat\w*|produc\w*|comput\w*|creat\w*)\b"
            r".{0,40}\b(?:multiple|two|several|different|distinct)\b"
            r".{0,45}\b(?:proofs?|outputs?|hashes?)\b",t,re.I))
        key_computation=bool(re.search(
            r"\b(?:us\w*|comput\w*|evaluat\w*)\b.{0,75}"
            r"\b(?:secret\s+key|\bsk\b|vrf)\b",t,re.I) and
            re.search(r"\b(?:trivial\w*|break\w*|two\s+distinct\s+outputs?)\b",
                      t,re.I))
        if (key_revealed and key_condemned) or key_computation:
            add("contradicts_rfc_3_3_sk_known","RFC 9381 Section 3.3",
                "Knowledge or ordinary use of an honestly generated SK does "
                "not by itself violate trusted uniqueness; a win requires "
                "two different accepting outputs for the SAME input.")
    unique=bool(re.search(r"\b(?:full|trusted)\s+uniqueness\b",t,re.I)
                or topic in {"1_full_uniqueness","2_trusted_uniqueness"})
    # RFC 9381 §3.1/3.3: two DIFFERENT outputs on ONE common input
    # break uniqueness. "Two inputs / same output" belongs to §3.2.
    # Require an affirmative recommended replacement of the win condition;
    # merely quoting the wrong definition to criticize it is not enough.
    collision_win=bool(re.search(
        r"\buniqueness\s+requires?\b.{0,100}"
        r"\b(?:two|2)\s+(?:different|distinct)\s+inputs?\b"
        r".{0,110}\b(?:same|equal|identical)\s+outputs?\b|"
        r"\bshould\s+win\b.{0,100}\b(?:same|equal)\s+outputs?\b|"
        r"\b(?:win|winning|wins?)\b.{0,70}\b(?:producing|finding)\b"
        r".{0,30}\b(?:a\s+)?collision\b|"
        r"\b(?:win|winning|wins?)\b.{0,90}\by\s*=\s*y['′]|"
        r"\b(?:should|must)\b.{0,75}\b(?:producing|finding)\b"
        r".{0,30}\b(?:a\s+)?collision\b|"
        r"\bnot\s+by\s+producing\s+(?:two\s+)?distinct\s+outputs\b|"
        r"\binverted\s+win\s+condition\b.{0,260}\bcollision\b",
        t,re.I))
    if unique and collision_win and not quoted_error:
        add("contradicts_rfc_3_1_uniqueness_is_not_collision",
            "RFC 9381 Sections 3.1, 3.2 and 3.3",
            "Objection substitutes collision resistance (different inputs, "
            "same output) for uniqueness (same input, different accepting "
            "outputs). Withhold this correction from the author.")
    # A reviewer cannot declare trusted uniqueness broken merely because
    # the target adversary receives or uses the honestly generated SK.
    # Knowledge of SK is part of RFC §3.3, not a second-output attack.
    key_access=bool(re.search(
        r"\b(?:knowledge\s+of|access\s+to|knows?|has|given|receives?|"
        r"uses?|using|full\s+knowledge\s+of)\b.{0,60}"
        r"\b(?:sk|secret\s+key)\b|"
        r"\b(?:sk|secret\s+key)\b.{0,60}"
        r"\b(?:access|knowledge|known|revealed|given)\b",t,re.I))
    condemns_key=bool(re.search(
        r"\b(?:trivial\w*|easily|simply|break\w*|undermin\w*|"
        r"can\s+produce\s+(?:two|collisions?)|"
        r"can\s+compute\s+.{0,50}collisions?)\b|"
        r"\b(?:generat\w*|produc\w*|comput\w*|creat\w*)\b"
        r".{0,40}\b(?:multiple|two|several|different|distinct)\b"
        r".{0,45}\b(?:proofs?|outputs?|hashes?)\b",t,re.I))
    concealed_key=bool(re.search(
        r"\b(?:cannot|not|must\s+not)\s+"
        r"(?:compute|obtain|learn|know|receive)\s+"
        r"(?:the\s+)?(?:sk|secret\s+key)\b|"
        r"\bkeeps?\s+(?:the\s+)?secret\s+"
        r"(?:key\s+)?hidden\b",t,re.I))
    if trusted and (concealed_key or (key_access and condemns_key)) and not quoted_error:
        add("contradicts_rfc_3_3_sk_known","RFC 9381 Section 3.3",
            "The trusted-uniqueness adversary may know and use the honestly "
            "generated SK. This alone cannot produce two different accepting "
            "outputs for one input.")
    # A second valid proof with the SAME output is permitted. Mark only
    # objections that incorrectly demand unique proofs regardless of output.
    proof_only=bool(re.search(
        r"\b(?:no\s+two\s+(?:distinct\s+)?(?:valid\s+)?proofs?|"
        r"unique\s+proofs?|uniqueness\s+of\s+proofs?|"
        r"(?:pi1|π1)\s*(?:!=|≠)\s*(?:pi2|π2))\b"
        r".{0,160}\b(?:regardless\s+of\s+(?:the\s+)?output|"
        r"must\s+(?:not\s+)?exist|requirement|must|"
        r"even\s+if\s+(?:the\s+)?outputs?\s+(?:is|are)\s+(?:the\s+)?same)\b|"
        r"\b(?:ignoring|ignores?|does\s+not\s+consider)\b"
        r".{0,80}\b(?:requirement|must|no\s+two)\b"
        r".{0,80}\b(?:distinct\s+)?(?:valid\s+)?proofs?\b",
        t,re.I))
    if unique and proof_only and not quoted_error:
        add("not_required_unique_proofs","RFC 9381 Sections 3.1 and 3.3",
            "Uniqueness forbids two different accepted OUTPUTS for one input; "
            "multiple proofs for the same output are not a uniqueness break.")
    # For §3.4 the challenge is deliberately output-only. Detect objections
    # claiming that omission itself leaks the hidden bit. Do not flag a
    # correct objection that demands withholding the proof in both worlds.
    says_must_omit=bool(re.search(
        r"\b(?:must|should|is|are)\s+(?:be\s+)?"
        r"(?:provided|given|returned|revealed|output)\s+without\b"
        r".{0,40}\bproof\b|"
        r"\b(?:must|should)\s+not\s+(?:return|reveal|provide|include)"
        r".{0,45}\bproof\b|"
        r"\bwithout\s+(?:a|its|the)\s+proof\b.{0,40}"
        r"\b(?:as|because|since)\b.{0,65}\bverif\w*\b"
        r".{0,65}\b(?:distinguish\w*|trivial\w*)\b",t,re.I))
    omitted=bool(re.search(
        r"\b(?:omit\w*|omis\w*|absen\w*|miss\w*|lack\w*|without|no|reject\w*)\b"
        r".{0,95}\bproof\b|\babsence\s+of\s+(?:a\s+)?valid\s+proof\b",t,re.I))
    causal=bool(re.search(
        r"\b(?:distinguish\w*|trivial\w*|detect\w*|"
        r"distinguishing\s+advantage)\b",t,re.I))
    # Scope guard to avoid confusing a missing proof for an unrelated
    # oracle evaluation with the intentionally proofless target challenge.
    challenge_scope=bool(re.search(r"\b(?:challenge|target\s+output|"
                                   r"target\s+input|π\s*\*|pi\s*\*)\b",t,re.I))
    direct_missing=bool(re.search(
        r"\b(?:no|without|missing|lacks?)\b.{0,40}\bproof\b"
        r".{0,90}\b(?:adversary|it)\b.{0,50}"
        r"\b(?:can|could|would)\b.{0,50}"
        r"\b(?:distinguish\w*|trivial\w*|eas\w*)\b",t,re.I))
    # A reviewer who notices MISSING post-challenge target-query
    # restrictions is raising a legitimate oracle-freshness issue.
    # Do not misread "without proof ... distinguish" as blaming the
    # intentionally proofless challenge.
    points_to_later_query_gap=bool(
        re.search(r"\b(?:quer\w*|evaluation\s+oracle)\b",t,re.I)
        and re.search(r"\b(?:after|later|post.challenge|subsequent)\b",t,re.I)
        and re.search(r"\b(?:does\s+not|not|fails?\s+to|omit\w*|"
                      r"unspecified|unclear|whether|allowed|permitted)\b",t,re.I))
    if pseudo and omitted and causal and (challenge_scope or direct_missing) and not (
            says_must_omit or quoted_error or points_to_later_query_gap):
        add("contradicts_rfc_3_4_no_challenge_proof",
            "RFC 9381 Section 3.4",
            "Objection treats the deliberately omitted challenge proof as a "
            "distinguishing leak; both challenge worlds omit it.")
    return list({x["kind"]:x for x in notes}.values())


def objection_scope_noise(question: str, issue: str, topic: str = "") -> str | None:
    """Very narrow, advisory VRF *definition* review-scope exclusions.

    These are excluded from author revision prompts, not deleted from the
    original record. Never use this for concrete construction-specific
    counterexamples or protocol proofs.
    """
    if (not re.search(r"\bVRF\b|verifiable random function",question,re.I)
            or not isinstance(issue,str)):
        return None
    text=" ".join(issue.split())
    if (re.search(r"\b(?:PPT|polynomial.time)\b",text,re.I) and
        re.search(r"\b(?:no|omit\w*|lack\w*|missing|fail\w*)\b.{0,125}"
                  r"\b(?:explicit\s+)?(?:bound|limit|number)\b.{0,70}"
                  r"\b(?:queries|oracle|computational\s+resources?)\b",text,re.I)
            and not re.search(r"\b(?:superpolynomial|unbounded\s+adversary)\b",
                              text,re.I)):
        return "ppt_resource_bounds_implicit"
    if (re.search(r"\b(?:eval|evaluation)\b.{0,30}\b(?:oracle|sk)\b|"
                  r"\boracle\b.{0,65}\b(?:secret\s+key|sk)\b",text,re.I) and
        re.search(r"\b(?:implicitly?\s+assumes?|effectively|indirect\s+access|"
                  r"requires?\s+(?:the\s+)?adversary)\b.{0,95}"
                  r"\b(?:knows?|given|access|expos\w*|reveals?)\b"
                  r".{0,50}\b(?:secret\s+key|sk)\b",text,re.I)):
        return "evaluation_oracle_does_not_reveal_sk"
    if (re.search(r"\blinear\s+combinations?\b.{0,110}"
                  r"\b(?:inputs?|queries|challenge)\b",text,re.I) and
        re.search(r"\b(?:lattice.based|some\s+constructions?|many\s+"
                  r"constructions?)\b",text,re.I) and
        not re.search(r"\b(?:explicit\s+attack|counterexample|"
                      r"concrete\s+scheme|named\s+construction)\b",text,re.I)):
        return "scheme_specific_attack_not_definition_gap"
    return None


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
    r"\b(?:forbid\w*|may\s+not|cannot|must\s+not|never|"
    r"not\s+allow\w*|disallow\w*|prohibit\w*)\b"
    r".{0,90}\b(?:quer\w*|ask\w*|eval(?:uate|uation)?)\b"
    r".{0,105}(?:x\s*\*|alpha\s*\*|α\s*\*|"
    r"target\s+(?:input|alpha)|challenge\s+input)|"
    r"\b(?:x\s*\*|alpha\s*\*|α\s*\*|"
    r"target\s+(?:input|alpha)|challenge\s+input)\b"
    r".{0,80}\b(?:cannot|must\s+not|never|forbid\w*|disallow\w*)\b"
    r".{0,50}\bquer\w*\b|"
    r"\b(?:must\s+not|cannot|never)\b.{0,30}\bquer\w*\b"
    r".{0,25}(?:alpha\s*\*|α\s*\*|x\s*\*)"
    r".{0,65}\b(?:after|post.challenge)\b",re.I)

SK_DISCLOSED = re.compile(
    # A positive grant is required. "given only pk (never sk)" must NOT match.
    r"\b(?:(?<!not\s)(?<!never\s)(?<!without\s)gives?\s+both\s+pk\s+and\s+sk|"
    r"(?:adversary|attacker)\s+"
    r"(?:is\s+given|receives|gets|knows|may\s+know)\s+"
    r"(?:(?!\b(?:not|never|without|only\s+pk)\b).){0,55}"
    r"\b(?:sk|secret\s+key)\b|"
    r"(?<!not\s)(?<!never\s)(?<!without\s)gives?\s+(?:the\s+)?adversary\s+"
    r"(?:(?!\b(?:not|never|without|only\s+pk)\b).){0,55}"
    r"\b(?:sk|secret\s+key)\b)",re.I)
MALFORMED_PK = re.compile(
    r"\b(?:malform\w*|malicious|arbitrary)\b.{0,75}"
    r"\b(?:public\s+key|pk)\b|"
    r"\b(?:public\s+key|pk)\b.{0,65}"
    r"\b(?:malform\w*|malicious|arbitrary)\b",re.I)
FULL_PK_SCOPE = re.compile(
    r"\b(?:malicious\w*|arbitrary|any\s+(?:possible\s+)?public|"
    r"adversarially\s+(?:chosen|selected))\b.{0,55}"
    r"\b(?:public\s+key|pk|keys?)\b|"
    r"\b(?:public\s+key|pk|keys?)\b.{0,55}"
    r"\b(?:malicious\w*|arbitrary|adversarially)\b|"
    r"\badversar\w*\s+(?:choos\w*|select\w*|outputs?|produc\w*|"
    r"picks?|suppl\w*)\b.{0,35}"
    r"\b(?:a\s+)?(?:vrf\s+)?(?:public\s+key|pk)\b|"
    r"\bchallenger\s+generates\s+no\s+keys\b",re.I)



def partition_addressed_objections(objections: list[dict]) -> tuple[list[dict],list[dict]]:
    """Advisory: identify complaints answered *in the cited claim's own text*.

    A source quotation is only provenance: lexical coverage never proves
    that the entire game is correct. Raw objections remain in stored records.
    """
    addressed,unresolved=[],[]
    for item in objections:
        issue=str(item.get("issue") or "")
        # Use the claimed STATEMENT only; an associated raw source quote can
        # contain the negative phrasing the objection is criticizing.
        target=str(item.get("target_statement") or item.get("target_text") or "")
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
        if (not correction and topic=="3_pseudorandomness" and
                re.search(r"\b(?:all|any|every)\s+post.?challenge\s+quer\w*|"
                          r"\bforbids?\s+(?:all|any)\s+post.?challenge\b",
                          issue,re.I)
                and re.search(
                    r"(?:α\s*\*|alpha\s*\*|x\s*\*|m\s*\*)"
                    r".{0,105}(?:before\s+or\s+after|after\s+the\s+challenge)",
                    target,re.I)):
            correction="only_target_input_forbidden_after_challenge"
        if not correction and topic=="2_trusted_uniqueness" and re.search(
            r"\b(?:not|never|missing|lacks?|without|only\s+pk)\b"
            r".{0,65}\b(?:sk|secret\s+key)\b",issue,re.I):
            if (SK_DISCLOSED.search(target) and not SK_DISCLOSED.search(issue)
                    and not re.search(r"\b(?:never|not|only\s+pk)\b"
                                      r".{0,45}\b(?:revealed|given|knows?)\b"
                                      r".{0,45}\b(?:sk|secret\s+key)\b",
                                      target,re.I)):
                correction="target_secret_key_disclosed"
        if (not correction and topic=="1_full_uniqueness"
                and MALFORMED_PK.search(issue)
                and re.search(r"\b(?:verify|verification|accept|outputs?)\b",
                              issue,re.I)
                and FULL_PK_SCOPE.search(target)):
            # A malicious public key making two different outputs verify
            # would be an attack against full uniqueness. The definition
            # already quantifies over that key, not excludes it.
            correction="malformed_pk_is_covered_by_full_uniqueness"
        clean={k:v for k,v in item.items()
               if k not in {"target_text","target_statement"}}
        if correction:
            addressed.append(dict(clean,
                advisory_status="already_addressed_by_claim",
                matched_requirement=correction))
        else:
            unresolved.append(clean)
    return addressed,unresolved

def _objection_signature(issue: str) -> str | None:
    """Specific repeated reviewer misconceptions despite wording changes."""
    t=" ".join(issue.split()).casefold()
    if (MALFORMED_PK.search(t) and
            re.search(r"\b(?:verify|verification|accept|outputs?)\b",t)):
        return "malformed_pk_verifies_everything"
    if (re.search(r"\b(?:proofs?|π1|π2|pi1|pi2)\b",t)
            and re.search(r"\b(?:valid|same\s+verif|verify|verification)\b",t)
            and re.search(r"\b(?:lack|not|missing|arbitrary|trivial|require)\b",t)):
        return "proofs_missing_validity_requirement"
    if (re.search(r"\b(?:secret\s+key|\bsk\b)\b",t)
            and re.search(r"\b(?:comput\w*|us\w*|evaluat\w*)\b",t)
            and re.search(r"\b(?:trivial|break\w*|two\s+distinct)\b",t)):
        return "sk_computation_misread_as_uniqueness_break"
    if (re.search(r"\b(?:omit\w*|omis\w*|absen\w*|miss\w*|without|lack\w*)\b"
                  r".{0,95}\bproof\b",t)
            and re.search(r"\b(?:distinguish\w*|trivial\w*|detect\w*)\b",t)):
        return "no_challenge_proof_misread_as_leak"
    return None


def deduplicate_objections(objections: list[dict], threshold: float = 0.90) -> list[dict]:
    """Display one representative per objection, retain all IDs/provenance.

    Similarity alone does not prove two criticisms are logically equivalent.
    Narrow signature matching covers common rephrasings of the same exact
    technical failure; the full original list is preserved in the run ledger.
    """
    distinct=[]
    for item in objections:
        statement=str(item.get("issue") or "")
        normalized=" ".join(statement.casefold().split())
        signature=_objection_signature(statement)
        match=None
        for existing in distinct:
            previous=" ".join(str(existing.get("issue") or "").casefold().split())
            previous_signature=_objection_signature(previous)
            same_specific_concern=(signature is not None and signature==previous_signature)
            if (same_specific_concern or
                    (item.get("topic")==existing.get("topic") and
                     SequenceMatcher(None,normalized,previous,autojunk=False).ratio()
                     >=threshold)):
                match=existing
                break
        if match is None:
            distinct.append(dict(item,duplicate_ids=list(item.get("duplicate_ids") or [])))
        else:
            match["duplicate_ids"].append(item.get("id"))
            match["duplicate_ids"].extend(item.get("duplicate_ids") or [])
    return distinct
