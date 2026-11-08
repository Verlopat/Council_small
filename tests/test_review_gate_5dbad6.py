"""Deterministic regressions for run 5dbad6d72bf348b8.

Never spend provider quota or treat model review as independent proof.
"""
import unittest
from types import SimpleNamespace

from council.extract import numbered_sentence_excerpt, source_sentence_ids
from council.families import endpoint_list
from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger, ClaimStatus, Objection
from council.prompts import prompt
from council.schemas import validate
from council.vrf_audit import objection_conflicts, objection_scope_noise
from council.vrf_sanity import scan_vrf_games

QUESTION="Explain full uniqueness, trusted uniqueness, and pseudorandomness security games for a lattice-based VRF."
REF_URI="https://www.rfc-editor.org/rfc/rfc9381.txt"


def kinds(issue,topic="1_full_uniqueness"):
    return {row["kind"] for row in objection_conflicts(
        QUESTION,"o1",issue,topic)}


class PreRevisionSafetyTests(unittest.TestCase):
    def test_o1_rejects_collision_as_uniqueness(self):
        issue=("The win condition 'winning if both verify and y≠y'' "
            "is inverted: uniqueness requires that no two distinct inputs "
            "produce the same output, so the adversary should win by "
            "producing a collision (y = y'), not by producing distinct "
            "outputs (y ≠ y').")
        self.assertIn("contradicts_rfc_3_1_uniqueness_is_not_collision",
                      kinds(issue))

    def test_o2_rejects_same_inverted_collision(self):
        issue=("The same inverted win condition (y≠y') appears in the "
               "trusted uniqueness game, and the phrase 'adversary may know "
               "the secret key after generation' is ambiguous: it does not "
               "specify whether the adversary receives the secret key "
               "before or after producing the collision, nor whether "
               "trusted uniqueness assumes perfect or computational "
               "uniqueness.")
        self.assertIn("contradicts_rfc_3_1_uniqueness_is_not_collision",
                      kinds(issue,"2_trusted_uniqueness"))

    def test_correct_critique_of_collision_remains_eligible(self):
        issue=("The proposal incorrectly defines uniqueness as two distinct "
               "inputs yielding the same output. It should instead require "
               "two valid DIFFERENT outputs for the SAME input.")
        self.assertNotIn("contradicts_rfc_3_1_uniqueness_is_not_collision",
                         kinds(issue))

    def test_sk_o6_and_o14_trusted(self):
        issue=("In the trusted uniqueness game the challenger gives both "
               "pk and sk to the adversary, yet the adversary is still "
               "required to win by finding two distinct valid outputs; "
               "with full knowledge of sk the adversary can compute Eval "
               "on any input and trivially produce collisions if the "
               "underlying function is not injective.")
        self.assertIn("contradicts_rfc_3_3_sk_known",
                      kinds(issue,"2_trusted_uniqueness"))

    def test_sk_o10_hidden_key_wrong(self):
        issue=("The definition does not guarantee that the adversary cannot "
               "compute the secret key (or otherwise obtain it) before "
               "outputting the collision, nor does it enforce any hardness "
               "assumption that keeps the secret hidden.")
        self.assertIn("contradicts_rfc_3_3_sk_known",
                      kinds(issue,"2_trusted_uniqueness"))

    def test_adversary_produces_key_is_explicit_choice(self):
        stmt=("Full uniqueness game defines a win when an adversary produces "
              "a VRF public key PK, a VRF input alpha, and two proofs pi1 "
              "and pi2 such that VRF_verify(PK, alpha, pi1) gives "
              "(VALID, beta1), VRF_verify(PK, alpha, pi2) gives "
              "(VALID, beta2), and beta1 != beta2.")
        flagged={x["kind"] for x in scan_vrf_games(
            QUESTION,[SimpleNamespace(id="p1:c1:repair",statement=stmt)])}
        self.assertNotIn("full_uniqueness_key_choice_unspecified",flagged)
        self.assertNotIn("full_uniqueness_key_generation",flagged)
        self.assertNotIn("uniqueness_collision_resistance_conflation",flagged)

    def test_injectivity_is_not_uniqueness(self):
        stmt=("Trusted uniqueness game with honest keys and known sk "
              "captures injectivity of the VRF function.")
        flagged={x["kind"] for x in scan_vrf_games(
            QUESTION,[SimpleNamespace(id="p3:c2",statement=stmt)])}
        self.assertIn("uniqueness_injectivity_conflation",flagged)

    def test_triage_withholds_o1_before_author(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"Full uniqueness game has a win "
                         "on two different outputs for one input.","gpt-oss"))
        ledger.add_claim(Claim("p1:c2",1,"Trusted uniqueness game uses "
                         "honest key generation and gives sk.","gpt-oss"))
        reviews=[
            Objection("o1","p1","p1:c1","nemotron",
                "Uniqueness requires no two distinct inputs produce the "
                "same output; the adversary should win by producing a "
                "collision (y = y').","wrong condition","compare §3.1"),
            Objection("o2","p1","p1:c1","nemotron",
                "The public key might be malformed; explain the verifier.",
                "underdetermined","check key"),
            Objection("o3","p1","p1:c2","nemotron",
                "Trusted uniqueness keeps the secret hidden, otherwise "
                "the game is trivially broken.","secret key revealed","check §3.3")]
        fake=SimpleNamespace(ledger=ledger,objections=reviews)
        refs={"3.1":{"section":"3.1"},"3.3":{"section":"3.3"}}
        withheld,eligible=FullCouncilRunner._triage_revision_objections(
            fake,QUESTION,refs)
        self.assertEqual([r["id"] for r in withheld],["o1","o3"])
        self.assertEqual([r.id for r in eligible],["o2"])
        self.assertEqual(len(fake.objections),3)
        self.assertTrue(all(r["reference_complete"] for r in withheld))

    def test_no_official_reference_does_not_claim_rfc_suppression(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"Full uniqueness game","gpt-oss"))
        review=Objection("o1","p1","p1:c1","nemotron",
            "Uniqueness requires two distinct inputs with same output; "
            "adversary should win by producing a collision.",
            "wrong","verify")
        fake=SimpleNamespace(ledger=ledger,objections=[review])
        withheld,eligible=FullCouncilRunner._triage_revision_objections(
            fake,QUESTION,{})
        self.assertEqual(withheld,[])
        self.assertEqual([x.id for x in eligible],["o1"])

    def test_indexed_complete_rfc_sections_only(self):
        responses={
            "3.1":{"section":"3.1","excerpt":"§3.1 full uniqueness",
                   "document_id":"rfc9381","source_uri":REF_URI,
                   "truncated":False},
            "3.3":{"section":"3.3","excerpt":"§3.3 trusted uniqueness",
                   "document_id":"another","source_uri":REF_URI,
                   "truncated":False},
            "3.4":{"section":"3.4","excerpt":"§3.4 partial",
                   "document_id":"rfc9381","source_uri":REF_URI,
                   "truncated":True},
        }
        called=[]
        idx=SimpleNamespace(rfc_section_excerpt=lambda section,max_chars:
            (called.append((section,max_chars)) or responses[section]))
        fake=SimpleNamespace(paper_index=idx)
        refs=FullCouncilRunner._rfc_game_references(fake,QUESTION)
        self.assertEqual(list(refs),["3.1"])
        self.assertEqual(called,[("3.1",10000),("3.3",10000),("3.4",10000)])

    def test_proposal_prompt_uses_rfc_and_capped_claims(self):
        text=prompt("proposal",{"question":QUESTION,
            "reference_sections":{"3.1":{"section":"3.1",
                                         "excerpt":"full uniqueness source"}}})
        self.assertIn("reference_sections",text)
        self.assertIn("authoritative security-game definitions",text)
        self.assertIn("AT MOST SIX",text)

    def test_revision_prompt_checks_reference_first(self):
        text=prompt("revision",{"reference_sections":{"3.1":{}}})
        self.assertIn("BEFORE",text)
        self.assertIn("Reject an objection",text)
        self.assertIn("[R1]",text)

    def test_revision_r_numbered_spans(self):
        revised=("[R1] Full uniqueness prohibits two accepted outputs "
                 "for one input. [R2] Trusted uniqueness assumes honest keys.")
        self.assertEqual(numbered_sentence_excerpt(revised,[1],tag="R"),
                         "Full uniqueness prohibits two accepted outputs "
                         "for one input.")
        self.assertEqual(source_sentence_ids(revised,
            "Trusted uniqueness assumes honest keys.",tag="R"),[2])
        parsed=validate("revision",{"revised_approach":revised,
                    "revised_claims":[{"claim_id":"p1:c1",
                                      "statement":"Full uniqueness.",
                                      "sentence_ids":[1]}]})
        self.assertEqual(parsed["revised_claims"][0]["sentence_ids"],[1])

    def test_apply_revision_preserves_sentence_provenance_but_not_evidence(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"Old full uniqueness definition.",
                              "gpt-oss"))
        events=[]
        fake=SimpleNamespace(ledger=ledger,extra_obligations=[],warnings=[],
            events=SimpleNamespace(record=lambda *a,**k:events.append((a,k))))
        p={"revised_approach":"[R1] Full uniqueness requires a single "
           "input and two different accepted outputs."}
        item={"claim_id":"p1:c1","statement":
                  "Full uniqueness prohibits multiple accepted outputs "
                  "for one fixed input.",
              "source_span":"", "sentence_ids":[1],"assumptions":[]}
        FullCouncilRunner._apply_revised_claim(
            fake,p,"p1:c1",item["statement"],item)
        changed=ledger.claims["p1:c1"]
        self.assertEqual(changed.version,2)
        self.assertEqual(changed.anchor_method,"revised_sentence_ids")
        self.assertEqual(changed.source_span,
            "Full uniqueness requires a single input and two different "
            "accepted outputs.")
        self.assertTrue(changed.needs_re_evaluation)
        self.assertEqual(changed.status,ClaimStatus.PROPOSED)
        self.assertTrue(any("alignment remain unchecked" in x
                            for x in fake.extra_obligations))

    def test_cohere_tries_command_a_then_plus_with_more_time(self):
        entries=endpoint_list("command")
        self.assertEqual([e.model for e in entries],
            ["command-a-03-2025","command-a-plus-05-2026"])
        self.assertTrue(all(e.timeout_seconds>=120 for e in entries))
        self.assertTrue(all(e.max_tokens>=6000 for e in entries))

    def test_review_noise_ppt_and_oracle(self):
        self.assertEqual(objection_scope_noise(QUESTION,
             "The PPT adversary has no explicit bound on number of "
             "evaluation oracle queries.", "3_pseudorandomness"),
             "ppt_resource_bounds_implicit")
        self.assertEqual(objection_scope_noise(QUESTION,
             "Using an evaluation oracle implemented by sk effectively "
             "gives the adversary indirect access to the secret key sk.",
             "1_full_uniqueness"),
             "evaluation_oracle_does_not_reveal_sk")
        self.assertEqual(objection_scope_noise(QUESTION,
             "The definition does not forbid linear combinations of inputs "
             "in many lattice-based constructions.",
             "3_pseudorandomness"),
             "scheme_specific_attack_not_definition_gap")


if __name__=="__main__":
    unittest.main()
