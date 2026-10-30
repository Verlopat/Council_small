"""Conservative VRF security-game red flags, not a proof checker.

These narrowly scoped checks flag explicit contradictions with RFC 9381 section
3. They may miss problems and must never be counted as independent evidence.
Input is untrusted LLM output; all findings are advisory only.
"""
from __future__ import annotations
import re

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
        text = " ".join(statement.split())
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
