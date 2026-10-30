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
        # RFC 9381 3.1 vs 3.2: uniqueness fixes ONE input and prohibits
        # DIFFERENT outputs. A claim about different inputs with ONE output
        # is collision resistance, regardless of whether it sounds plausible.
        is_unique = FULL.search(text) or TRUSTED.search(text)
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
        if PSEUDO.search(text) and re.search(
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
        if FULL.search(text) and re.search(
                r"\b(?:honest|honestly generated|trusted)\s+"
                r"(?:public\s+)?key\b",text,re.I) and not re.search(
                r"\b(?:malicious|adversarial|arbitrary)\s+"
                r"(?:public\s+)?keys?\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"full_uniqueness_honest_key_only",
                "message":"The definition appears restricted to honest "
                          "public keys. Full uniqueness must include "
                          "adversarially selected public keys.",
                "reference":"RFC 9381 Section 3.1"})
        if TRUSTED.search(text) and re.search(
                r"\b(?:malicious|adversarial)\s+key\s+generation\b",text,re.I):
            findings.append({
                "claim_id":cid,
                "kind":"trusted_uniqueness_malicious_key_contradiction",
                "message":"Trusted uniqueness does not require security "
                          "under malicious key generation; that stronger "
                          "condition belongs to full uniqueness.",
                "reference":"RFC 9381 Section 3.3"})
        # The game type can be valid even if the model uses signature
        # terminology; flag the ambiguity rather than silently equating APIs.
        if re.search(r"\bsigning\s+oracle\b",text,re.I) and (
                FULL.search(text) or TRUSTED.search(text) or PSEUDO.search(text)):
            findings.append({
                "claim_id":cid,"kind":"vrf_signing_oracle_terminology",
                "message":"The game specifies a signing oracle. Distinguish "
                          "ordinary VRF evaluation/proof access from a "
                          "signature oracle; uniqueness does not need an "
                          "oracle to define its two-output win condition.",
                "reference":"RFC 9381 Sections 3.1–3.4"})
        if TRUSTED.search(text) and re.search(
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
        if FULL.search(text) and re.search(
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
        if TRUSTED.search(text) and re.search(
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
        if PSEUDO.search(text):
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
        if PSEUDO.search(text) and re.search(r"\bgame\b",text,re.I):
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
            if not re.search(r"\bunqueried\b|\bfresh\b|"
                             r"\b(?:not|never)\s+quer(?:y|ied)\b|"
                             r"\bforbid.{0,45}quer|\bother\s+inputs?\b|"
                             r"\bexcept\s+(?:the\s+)?challeng",text,re.I):
                findings.append({
                    "claim_id":cid,"kind":"pseudorandomness_freshness_unspecified",
                    "message":"Challenge-input freshness and the prohibition "
                              "on asking its evaluation/proof oracle are not "
                              "specified in this claim.",
                    "reference":"RFC 9381 Section 3.4"})
        if FULL.search(text) and re.search(r"\bgame\b",text,re.I):
            if not re.search(r"adversar(?:y|ial).{0,85}"
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
        if FULL.search(text):
            if (re.search(r"challenger.{0,110}(?:key\s*gen(?:eration)?|"
                          r"keygen|generates?\s+(?:a\s+)?key\s*pair)", text, re.I)
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
        if TRUSTED.search(text) and re.search(r"\bgame\b",text,re.I):
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
        if TRUSTED.search(text) and re.search(r"trapdoor\s+oracle", text, re.I):
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
    # Only report each particular concern once per claim.
    return list({(row["claim_id"], row["kind"]): row
                 for row in findings}.values())
