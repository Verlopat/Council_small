"""Conservative VRF security-game red flags, not a proof checker.

These narrowly scoped checks flag explicit contradictions with RFC 9381 section
3. They may miss problems and must never be counted as independent evidence.
Input is untrusted LLM output; all findings are advisory only.
"""
from __future__ import annotations
import re
from council.definition_sources import topic_text

VRF = re.compile(r"\bVRFs?\b|verifiable random function", re.I)
PSEUDO = re.compile(r"pseudorandom|\bPRF\b", re.I)
FULL = re.compile(r"\bfull\s+uniqueness", re.I)
TRUSTED = re.compile(r"\btrusted\s+uniqueness", re.I)
# RFC §3.1 explicitly permits the adversary to *produce/find/output* the PK.
ADV_KEY = re.compile(
    r"\badversar\w*.{0,65}\b(?:produc\w*|output\w*|find\w*|"
    r"choos\w*|select\w*|generat\w*|submit\w*|suppl\w*)\b"
    r".{0,65}\b(?:vrf\s+)?(?:public\s+key|pk)\b|"
    r"\bno\s+adversary\s+can\s+find\s+(?:a\s+)?"
    r"(?:vrf\s+)?public\s+key\b|"
    r"\bfor\s+(?:any|every|all)\s+(?:vrf\s+)?public\s+keys?\b",
    re.I)


def game_topic(statement: str) -> str | None:
    """Most-specific named security-game topic; trusted outranks full."""
    t=topic_text(statement)
    if "trusted uniqueness" in t:
        return "trusted"
    if "full uniqueness" in t:
        return "full"
    if "pseudorandom" in t:
        return "pseudo"
    return None


def describes_game(statement: str) -> bool:
    """Skip cryptographic-assumption conjectures and model-only research claims."""
    t=topic_text(statement)
    if game_topic(t) is None:
        return False
    if re.search(r"\b(?:reduc(?:es?|ed|tion)|assumptions?|hardness|"
                 r"\bsis\b|\blwe\b|random\s+oracle\s+model)\b",t,re.I):
        return False
    return bool(re.search(
        r"\b(?:adversary|challenger|oracle|wins?|game|choos\w*|"
        r"receiv\w*|produces?|outputs?|proofs?|"
        r"requires?|forbids?|breaks?|broken|assumes?|"
        r"verif\w*|keygen)\b",t,re.I))


def scan_vrf_games(question: str, claims) -> list[dict]:
    if not VRF.search(question):
        return []
    findings = []
    for claim in claims:
        statement = getattr(claim, "statement", "")
        cid = getattr(claim, "id", "")
        if not isinstance(statement, str) or not isinstance(cid, str):
            continue
        text = topic_text(statement)
        if not describes_game(text):
            continue
        topic=game_topic(text)
        full_here=(topic=="full")
        trusted_here=(topic=="trusted")
        pseudo_here=(topic=="pseudo")
        # RFC 9381 3.1 vs 3.2: uniqueness fixes ONE input and prohibits
        # DIFFERENT outputs. A claim about different inputs with ONE output
        # is collision resistance, regardless of whether it sounds plausible.
        is_unique = full_here or trusted_here
        if is_unique:
            different_inputs = re.search(
                r"\b(?:two|2)\s+(?:distinct|different)\s+(?:VRF\s+)?inputs?\b"
                r"|\b(?:distinct|different)\s+(?:VRF\s+)?inputs?\b", text, re.I)
            same_output = re.search(
                r"\b(?:same|identical|equal|matching)\s+(?:VRF\s+)?"
                r"(?:hash\s+)?outputs?\b"
                r"|\b(?:VRF\s+)?outputs?\b.{0,30}"
                r"\b(?:same|identical|equal)\b", text, re.I)
            if different_inputs and same_output:
                findings.append({
                    "claim_id":cid,
                    "kind":"uniqueness_collision_resistance_conflation",
                    "message":"This uniqueness claim describes distinct inputs "
                              "yielding the same output: RFC 9381 Section 3.2 "
                              "calls that collision resistance. Uniqueness "
                              "(Sections 3.1/3.3) requires a common input "
                              "and two distinct verified outputs.",
                    "reference":"RFC 9381 Sections 3.1–3.3"})
        if is_unique and re.search(r"\binjectiv(?:e|ity)\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"uniqueness_injectivity_conflation",
                "message":"Injectivity across distinct inputs is the collision-"
                          "resistance notion in RFC 9381 Section 3.2; uniqueness "
                          "requires one fixed input and at most one accepted output.",
                "reference":"RFC 9381 Sections 3.1–3.3"})
        if is_unique and re.search(
                r"\b(?:trapdoor|secret\s+key)\b.{0,100}"
                r"\bverif(?:y|ies|ication)\b|"
                r"\bverif(?:y|ies|ication)\b.{0,100}"
                r"\b(?:trapdoor|secret\s+key)\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"uniqueness_secret_verifier",
                "message":"Public VRF verification is defined using the "
                          "public key. This claim appears to use a secret "
                          "trapdoor or key to verify outputs; inspect the "
                          "verifier interface.",
                "reference":"RFC 9381 Section 2"})
        if pseudo_here and re.search(
                r"\brandom\s+(?:challenge\s+)?(?:point|input)\b",
                text,re.I) and not re.search(
                r"\badversar(?:y|ial)\b.{0,85}"
                r"\b(?:choos|select|nominate)",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"pseudorandomness_random_target",
                "message":"The game appears to sample a random challenge "
                          "input; full VRF pseudorandomness allows the "
                          "adversary to choose its target input adaptively. "
                          "Selective security uses an earlier adversarial "
                          "commitment, not a random target.",
                "reference":"RFC 9381 Section 3.4"})
        if is_unique and len(text.split()) <= 5:
            findings.append({
                "claim_id":cid,
                "kind":"uniqueness_definition_underspecified",
                "message":"A label such as 'Full uniqueness property' is "
                          "not a security game definition. State the public "
                          "key choice, common input, two valid proofs and "
                          "different outputs explicitly.",
                "reference":"RFC 9381 Sections 3.1/3.3"})
        # A uniqueness *definition* cannot require injective evaluations
        # on all distinct inputs. That is the collision-resistance notion,
        # whether the model asserts an actual collision or its impossibility.
        if is_unique and different_inputs and re.search(
                r"\b(?:outputs?|hashes?)\b.{0,65}\b(?:differ|different|"
                r"distinct|unequal|not equal)\b|"
                r"\b(?:outputs?|hashes?)\s*(?:!=|≠)\b", text, re.I):
            findings.append({
                "claim_id":cid,
                "kind":"uniqueness_injectivity_conflation",
                "message":"The claim imposes different outputs for distinct "
                          "inputs. That is an injectivity/collision-resistance "
                          "condition, not VRF uniqueness, which fixes one "
                          "input and rules out two accepted outputs.",
                "reference":"RFC 9381 Sections 3.1–3.3"})
        if full_here and re.search(
                r"\b(?:honest|honestly generated|trusted)\s+"
                r"(?:public\s+)?key\b",text,re.I) and not ADV_KEY.search(text) and not re.search(
                r"\b(?:malicious|adversarial|arbitrary)\s+"
                r"(?:public\s+)?keys?\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"full_uniqueness_honest_key_only",
                "message":"The definition appears restricted to honest "
                          "public keys. Full uniqueness must include "
                          "adversarially selected public keys.",
                "reference":"RFC 9381 Section 3.1"})
        if trusted_here and re.search(
                r"\b(?:malicious|adversarial)\s+key\s+generation\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"trusted_uniqueness_malicious_key_contradiction",
                "message":"Trusted uniqueness does not require security "
                          "under malicious key generation; that stronger "
                          "condition belongs to full uniqueness.",
                "reference":"RFC 9381 Section 3.3"})
        # A uniqueness experiment has no pseudorandomness challenge.
        # Descriptions like "in each game the challenger selects a fresh
        # challenge input" incorrectly apply the VRF PR game universally.
        if re.search(r"\b(?:in|for)\s+(?:each|every|all)\s+(?:security\s+)?game\b",
                     text,re.I) and re.search(r"\bchalleng(?:e|er)\b",text,re.I):
            if re.search(r"\b(?:fresh|random|target|select|choos|input|proof)\b",
                         text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"vrf_challenge_in_every_game",
                    "message":"This claim applies a challenge-input step to "
                              "every VRF game. Uniqueness asks for two accepted "
                              "outputs for one fixed input; the fresh target "
                              "challenge belongs to pseudorandomness.",
                    "reference":"RFC 9381 Sections 3.1, 3.3 and 3.4"})
        if trusted_here and re.search(
                r"\b(?:game|requires?|restricts?|assumes?|prohibits?|ensures?)\b",
                text,re.I) and not re.search(
                r"\b(?:secret\s+key|private\s+key|SK|trapdoor)\b",text,re.I):
            findings.append({
                "claim_id":cid,"kind":"trusted_uniqueness_sk_knowledge_unspecified",
                "message":"Trusted uniqueness must hold for honestly "
                          "generated PK/SK even when the adversary knows "
                          "the target secret key. This claim does not "
                          "specify that capability; check the complete game.",
                "reference":"RFC 9381 Section 3.3"})
        if re.search(r"\b(?:the|our)\s+(?:lattice\s+(?:based\s+)?)?"
                r"(?:vrf\s+)?construction\s+uses?\b",text,re.I) and re.search(
                r"\b(?:trapdoor|gaussian|rounding|sis|lwe)\b",text,re.I):
            findings.append({
                "claim_id":cid,"kind":"vrf_construction_not_identified",
                "message":"The claim assigns concrete lattice mechanisms "
                          "to an unspecified construction. Identify a scheme "
                          "and evidence before accepting these primitives.",
                "reference":"construction-specific evidence required"})
        if is_unique:
            # VRF uniqueness requires different verified output values, not
            # merely different proofs of the same value.
            distinct_proofs = re.search(
                r"\b(?:two|2)\s+(?:syntactically\s+)?(?:distinct|different)"
                r"\s+proofs?\b|"
                r"(?:π|pi|proof)\s*[1₁]\s*(?:≠|!=|\\neq)\s*"
                r"(?:π|pi|proof)\s*[2₂]",text,re.I)
            distinct_values = re.search(
                r"\b(?:two|2)\s+(?:distinct|different)\s+"
                r"(?:valid\s+)?(?:vrf\s+)?(?:outputs?|values?)\b|"
                r"(?:y|β|beta|output)\s*[1₁]\s*(?:≠|!=|\\neq)\s*"
                r"(?:y|β|beta|output)\s*[2₂]|"
                r"\bdistinct\s+outputs?\b|"
                r"\bdifferent\s+outputs?\b",text,re.I)
            if distinct_proofs and not distinct_values:
                findings.append({
                    "claim_id":cid,"kind":"uniqueness_on_proofs",
                    "message":"Different proofs alone do not violate VRF "
                              "uniqueness. The win condition needs TWO "
                              "DIFFERENT OUTPUT VALUES that both verify "
                              "for the same public key and input.",
                    "reference":"RFC 9381 Sections 3.1 and 3.3"})
        if trusted_here and re.search(
                r"\bnever\s+(?:obtains?|learns?|gets?|receives?)\b.{0,45}"
                r"(?:secret\s+key|\bsk\b)|"
                r"\b(?:cannot|can\s+not|forbid\w*|prevent\w*)\b.{0,85}"
                r"\b(?:learn\w*|obtain\w*|receive\w*)\b.{0,45}"
                r"(?:secret\s+key|\bsk\b)|"
                r"\baborts?\s+if\b.{0,100}(?:secret\s+key|\bsk\b)|"
                r"\b(?:secret\s+key|\bsk\b)\b.{0,40}"
                r"\b(?:never\s+(?:learned|revealed|known)|is\s+hidden)\b",
                text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"trusted_uniqueness_sk_secrecy_contradiction",
                "message":"The claim incorrectly requires the target secret "
                          "key to remain hidden. Trusted uniqueness must "
                          "hold even if the adversary knows the honestly "
                          "generated secret key.",
                "reference":"RFC 9381 Section 3.3"})
        if pseudo_here:
            if re.search(r"\bverification\s+oracle\b",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"prf_verification_oracle",
                    "message":"Public verification requires only pk and can be "
                              "run locally. A special verification oracle is "
                              "unnecessary and may signal a mis-specified game.",
                    "reference":"RFC 9381 Sections 2 and 3.4"})
            if (re.search(r"\b(?:evaluation\s+)?oracle\b.{0,100}"
                          r"\b(?:returns?|responds?|answers?|replies?|outputs?)\b"
                          r".{0,65}\b(?:random|simulat\w*)\b",text,re.I)
                    or re.search(r"\b(?:oracle\s+responses?|ordinary\s+queries)\b"
                                 r".{0,90}\b(?:random|simulat\w*)\b",text,re.I)):
                findings.append({
                    "claim_id":cid,"kind":"oracle_distribution_conflation",
                    "message":"Ordinary VRF evaluation oracle outputs must "
                              "remain REAL output-proof pairs in both worlds. "
                              "Only the fresh challenge output is real-or-random.",
                    "reference":"RFC 9381 Section 3.4"})
        # The game type can be valid even if the model uses signature
        # terminology; flag the ambiguity rather than silently equating APIs.
        if re.search(r"\bsigning\s+oracle\b",text,re.I) and (
                full_here or trusted_here or pseudo_here):
            findings.append({
                "claim_id":cid,"kind":"vrf_signing_oracle_terminology",
                "message":"The game specifies a signing oracle. Distinguish "
                          "ordinary VRF evaluation/proof access from a "
                          "signature oracle; uniqueness does not need an "
                          "oracle to define its two-output win condition.",
                "reference":"RFC 9381 Sections 3.1–3.4"})
        if trusted_here and re.search(
                r"\b(?:different|other)\s+(?:identit(?:y|ies)|"
                r"instances?|secret\s+keys?|keys?)\b|"
                r"\b(?:some|other)\s+keys?\s+but\s+not\s+"
                r"(?:the\s+)?target",text,re.I):
            findings.append({
                "claim_id":cid,"kind":"trusted_uniqueness_wrong_key_target",
                "message":"Trusted uniqueness must hold even when the "
                          "adversary knows the target's honestly generated "
                          "secret key. Knowledge of other identities' keys "
                          "is not the defining experiment.",
                "reference":"RFC 9381 Section 3.3"})
        if full_here and re.search(
                r"\b(?:all|these|above)\s+(?:games|definitions)\b.{0,110}"
                r"\bhonest[- ]key\b|"
                r"\bfull\s+uniqueness\b.{0,180}"
                r"\b(?:restricted to|defined for)\s+(?:the\s+)?honest[- ]key",
                text,re.I):
            findings.append({
                "claim_id":cid,"kind":"full_uniqueness_honest_key_contradiction",
                "message":"Full uniqueness must cover adversarially chosen "
                          "public keys; describing all games as honest-key "
                          "games contradicts this condition.",
                "reference":"RFC 9381 Section 3.1"})
        if trusted_here and re.search(
                r"\bnever\s+(?:leaked|exposed|revealed|disclosed)\b|"
                r"\b(?:kept|remains?)\s+secret\b|"
                r"\bwithout\s+(?:access\s+to\s+|knowledge\s+of\s+|the\s+)"
                r"(?:secret\s+key|SK)\b", text,re.I):
            findings.append({
                "claim_id":cid,"kind":"trusted_uniqueness_secret_key_contradiction",
                "message":"This trusted-uniqueness claim appears to require "
                          "the secret key to remain hidden. RFC 9381 Section "
                          "3.3 explicitly requires uniqueness even when "
                          "honestly generated SK and PK are known. This is "
                          "a likely definition contradiction, not merely an "
                          "omitted assumption.",
                "reference":"RFC 9381 Section 3.3"})
        if (re.search(r"\buniqueness\b",text,re.I)
                and re.search(r"uniquely\s+determined\s+by.{0,65}"
                              r"(?:input|x).{0,45}(?:secret\s+key|SK)",
                              text,re.I)):
            findings.append({
                "claim_id":cid,"kind":"uniqueness_wrong_key_quantifier",
                "message":"VRF uniqueness constrains accepted outputs for "
                          "each fixed public key and input, rather than "
                          "assuming the verifier knows or trusts a secret "
                          "key. Check the intended key quantifier.",
                "reference":"RFC 9381 Section 3.1"})
        if pseudo_here:
            # A challenger should not disclose a valid proof for the
            # pseudorandomness challenge. Flag only affirmative descriptions,
            # not cautions warning that a proof must NOT be returned.
            leaked_proof = (
                re.search(r"(?:random|uniform|challenge|b\s*=\s*1).{0,260}"
                          r"(?:simulated\s+proof|proof\s+that\s+always\s+verifies)",
                          text, re.I) is not None)
            has_negation = (
                re.search(r"\b(?:no|not|never|without|forbidden|mustn't)\b"
                          r".{0,85}(?:simulated\s+proof|proof\s+that\s+always\s+verifies)",
                          text, re.I) is not None)
            if leaked_proof and not has_negation:
                findings.append({
                    "claim_id": cid,
                    "kind": "challenge_proof_leak",
                    "message": "Proposed pseudorandomness game appears to "
                               "return a validating/simulated proof for the "
                               "random challenge. Standard VRF games reveal "
                               "only the challenge output; review this game.",
                })
            # The challenge bit is not supposed to replace the *entire*
            # evaluation oracle with random values and simulated proofs.
            if (re.search(r"\b(?:all|every|each)\b.{0,55}\b(?:quer(?:y|ies)|"
                          r"oracle responses?)\b", text, re.I)
                    and re.search(r"\b(?:random|uniform)\b.{0,75}\bproof", text, re.I)):
                findings.append({
                    "claim_id": cid,
                    "kind": "oracle_distribution_conflation",
                    "message": "Description may randomize ordinary evaluation "
                               "oracle responses rather than only the "
                               "fresh challenge output; inspect oracle rules.",
                })
        # Advantage formulas are not stand-alone game interfaces; do not
        # flag missing oracle/freshness merely because a formula says 'game'.
        describes_game=(bool(re.search(
            r"\b(?:challeng(?:e|er)|oracle|quer(?:y|ied|ies)|game)\b",
            text,re.I)) and not bool(re.search(
            r"\badvantage\b.{0,150}(?:pr\s*\[|probability)",
            text,re.I)))
        if pseudo_here and describes_game:
            if (re.search(r"\bPRF\s+(?:output\s+)?distribution\b",text,re.I)
                    and not re.search(r"\buniform(?:ly)?\s+random\b",text,re.I)):
                findings.append({
                    "claim_id":cid,"kind":"pseudorandomness_wrong_ideal_distribution",
                    "message":"The ideal VRF pseudorandomness challenge is uniform "
                              "over the output space, not sampled from a PRF "
                              "distribution. Review the exact game.",
                    "reference":"RFC 9381 Section 3.4"})
            if not re.search(r"\bevaluation\s+oracle\b|\boracle\b|"
                             r"\bquer(?:y|ies)\b.{0,100}\bproof\b|"
                             r"\bproof\b.{0,100}\bother\s+inputs?\b",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"pseudorandomness_oracle_unspecified",
                    "message":"No evaluation oracle giving real output-proof "
                              "pairs for other inputs appears in this claim. "
                              "Check the complete game.",
                    "reference":"RFC 9381 Section 3.4"})
            if not (re.search(r"\bselective\s+pseudorandom",text,re.I)
                    and not re.search(r"\bfull\s+pseudorandom",text,re.I)) and not re.search(r"\bunqueried\b|\bfresh\b|"
                             r"\b(?:not|never)\s+quer(?:y|ied)\b|"
                             r"\bforbid.{0,45}quer|\bother\s+inputs?\b|"
                             r"\bexcept\s+(?:the\s+)?challeng",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"pseudorandomness_freshness_unspecified",
                    "message":"Challenge-input freshness and the prohibition "
                              "on asking its evaluation/proof oracle are not "
                              "specified in this claim.",
                    "reference":"RFC 9381 Section 3.4"})
        if full_here and re.search(r"\bgame\b",text,re.I):
            if not ADV_KEY.search(text) and not re.search(r"adversar(?:y|ial).{0,85}"
                             r"(?:choos|select|generat|suppl).{0,50}"
                             r"(?:key|PK|public)\b|"
                             r"(?:PK|public\s+key).{0,40}chosen\s+by\s+"
                             r"(?:the\s+)?adversary|"
                             r"\b(?:malicious|adversarial|arbitrary)\s+"
                             r"(?:public\s+)?keys?\b|"
                             r"\bany\s+(?:valid\s+)?public\s+key\b",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"full_uniqueness_key_choice_unspecified",
                    "message":"Full uniqueness includes adversarially chosen "
                              "public keys, which are not explicitly covered "
                              "by this claim. Check the full game.",
                    "reference":"RFC 9381 Section 3.1"})
            if (re.search(r"\by\s*(?:\^\s*)?\*|\by\s*_\s*\*",text,re.I)
                    and not re.search(r"\b(?:two|both)\b.{0,70}\b(?:proof|"
                                      r"valid|output)\b|π1|pi1|pi_1",text,re.I)):
                findings.append({
                    "claim_id":cid,"kind":"full_uniqueness_challenger_reference",
                    "message":"A reference output y* and one alternative do "
                              "not specify the full uniqueness win condition: "
                              "two different accepting outputs for one input "
                              "and adversarially selected public key.",
                    "reference":"RFC 9381 Section 3.1"})
        if full_here:
            if (re.search(r"challenger.{0,110}(?:key\s*gen(?:eration)?|"
                          r"keygen|generates?\s+(?:a\s+)?key\s*pair)", text, re.I)
                    and not ADV_KEY.search(text)
                    and not re.search(r"adversar(?:y|ial).{0,60}(?:choos|generat|"
                                      r"select).{0,30}(?:pk|public key|key pair)",
                                      text, re.I)):
                findings.append({
                    "claim_id": cid,
                    "kind": "full_uniqueness_key_generation",
                    "message": "Full uniqueness permits adversarial choice of "
                               "the public key; a game restricted to honest "
                               "challenger key generation is the trusted-key "
                               "variant. Review key-generation quantifiers.",
                })
        if trusted_here and re.search(r"\bgame\b",text,re.I):
            if not re.search(r"\bhonest(?:ly)?\b|\bkeygen\b|"
                             r"\bkey\s+gen(?:eration)?\b|"
                             r"\bproper(?:ly)?\s+generated\b",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"trusted_uniqueness_key_origin_unspecified",
                    "message":"Trusted uniqueness presumes honestly "
                              "generated keys, even if the adversary knows "
                              "the secret key. The assumption is missing here.",
                    "reference":"RFC 9381 Section 3.3"})
            if re.search(r"\bsame\s+(?:win\s+)?condition\s+as\b|"
                         r"\bsame\s+as\s+(?:the\s+)?full\b",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"trusted_uniqueness_inherited_game",
                    "message":"This claim references another game's win "
                              "condition without independently specifying "
                              "two different accepting outputs for one input.",
                    "reference":"RFC 9381 Section 3.3"})
        if trusted_here and re.search(r"trapdoor\s+oracle", text, re.I):
            findings.append({
                "claim_id": cid,
                "kind": "trusted_uniqueness_trapdoor_oracle",
                "message": "Trusted uniqueness is defined by honestly "
                           "generated keys, not a special trapdoor oracle. "
                           "Review which key material the adversary learns.",
            })
        if ("correctness" in text.lower() and "game" in text.lower()
                and re.search(r"adversary\s+wins?.{0,110}(?:different|differs|"
                              r"y'\s*!=|y\s*≠)", text, re.I)):
            findings.append({
                "claim_id": cid,
                "kind": "correctness_as_forgery",
                "message": "An adversarial win by a second valid but different "
                           "output is a uniqueness-style condition, not the "
                           "usual honest-evaluation correctness property.",
            })

        # Conditional win probabilities are not automatically the VRF
        # distinguishing advantage. This is advisory, not a formal parser.
        win_cond=re.findall(
            r"\bPr\s*\[\s*[^\]]*\bwins?\b\s*\|\s*b\s*=\s*[01]\s*\]",
            statement,re.I)
        if re.search(r"\badvantage\b",statement,re.I) and len(win_cond)>=2:
            findings.append({
                "claim_id":cid,"kind":"advantage_on_win",
                "message":"The proposed advantage compares conditional "
                          "win probabilities. State a single distinguishing "
                          "event: |Pr[b'=1|b=0] - Pr[b'=1|b=1]|, "
                          "or |Pr[b'=b] - 1/2| with the proper convention.",
                "reference":"RFC 9381 Section 3.4"})
    # Only report each particular concern once per claim.
    return list({(row["claim_id"], row["kind"]): row
                 for row in findings}.values())
