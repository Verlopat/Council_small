"""Regression cases from run 8214fcec6ae94660 (offline only).

The judge tests require quotes for adverse dismissals; no model consensus
or pattern match is treated as cryptographic verification.
"""
import asyncio
from types import SimpleNamespace
import unittest

from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger, Objection
from council.definition_sources import is_vrf_definition_question
from council.schemas import validate
from council.structured import response_format
from council.vrf_audit import objection_conflicts, partition_addressed_objections


Q="Explain full uniqueness, trusted uniqueness, and pseudorandomness security games for a lattice-based VRF."


class GroundedObjectionTests(unittest.TestCase):
    def test_o17_claim_that_sk_trivially_breaks(self):
        issue=(
            'The claim that "Trusted uniqueness assumes honest key generation '
            'and allows the adversary to know SK" is inconsistent with the '
            'cited game (p2:r14) which gives the adversary both PK and SK, but '
            'the winning condition still references verification with PK only. '
            'Knowledge of SK trivially enables computing the secret VRF output, '
            'breaking uniqueness without violating the verification condition.'
        )
        kinds={x["kind"] for x in objection_conflicts(Q,"o17",issue,
                                        "2_trusted_uniqueness")}
        self.assertIn("contradicts_rfc_3_3_sk_known",kinds)

    def test_audit4_sk_produces_multiple_valid_proofs(self):
        issue=("Unaddressed objection o10/o21: p3:c2 gives the adversary "
               "both PK and SK; it fails to address how uniqueness is maintained "
               "if the adversary can simply use SK to generate multiple valid "
               "proofs/outputs for the same input.")
        kinds={x["kind"] for x in objection_conflicts(Q,"audit:4",issue,
                                      "2_trusted_uniqueness")}
        self.assertIn("contradicts_rfc_3_3_sk_known",kinds)

    def test_audit6_no_required_unique_proofs(self):
        issue=("Unaddressed objection o6/o16: p2:r13 and p2:c1 focus only on "
               "distinct outputs (beta1 != beta2), ignoring the standard "
               "requirement that no two distinct valid proofs (pi1 != pi2) "
               "should exist for the same input, regardless of the output.")
        kinds={x["kind"] for x in objection_conflicts(Q,"audit:6",issue,
                                       "1_full_uniqueness")}
        self.assertIn("not_required_unique_proofs",kinds)

    def test_genuine_proof_only_gap_is_not_false_conflict(self):
        issue=("The game says two different proofs for the same input cause a "
               "win, but it forgets to require that the two verified OUTPUTS "
               "are different, so this is a proof-only definition.")
        kinds={x["kind"] for x in objection_conflicts(Q,"o3",issue,
                                       "1_full_uniqueness")}
        self.assertNotIn("not_required_unique_proofs",kinds)

    def test_malformed_pk_is_covered_by_adversary_picks_key(self):
        suspect={"id":"o9","topic":"1_full_uniqueness",
            "issue":("The adversary may choose a malformed PK and make "
                     "VRF_verify accept arbitrary proofs, trivially breaking "
                     "uniqueness because the challenger generates no keys."),
            "target_statement":("Full uniqueness game: the challenger "
                                "generates no keys; the adversary chooses "
                                "PK, alpha and two proofs that verify to "
                                "different outputs.")}
        addressed,remaining=partition_addressed_objections([suspect])
        self.assertFalse(remaining)
        self.assertEqual(addressed[0]["matched_requirement"],
                         "malformed_pk_is_covered_by_full_uniqueness")

    def test_only_target_is_barred_after_challenge(self):
        suspect={"id":"o11","topic":"3_pseudorandomness",
            "issue":("The statement says the adversary must never query "
                     "alpha* before or after the challenge, but standard "
                     "pseudorandomness games allow all post-challenge queries "
                     "on other inputs and prohibiting any post-challenge "
                     "queries would weaken security."),
            "target_statement":("Full pseudorandomness gives a challenger "
                                "oracle and requires never querying alpha* "
                                "before or after the challenge, but permits "
                                "queries to other inputs.")}
        addressed,remaining=partition_addressed_objections([suspect])
        self.assertFalse(remaining)
        self.assertEqual(addressed[0]["matched_requirement"],
                         "only_target_input_forbidden_after_challenge")

    def test_missing_freshness_objection_must_stay_open(self):
        obj={"id":"o3","topic":"3_pseudorandomness",
             "issue":"The claim does not forbid queries on alpha* after challenge.",
             "target_statement":"Full pseudorandomness returns beta* without proof."}
        addressed,open_=partition_addressed_objections([obj])
        self.assertEqual(addressed,[])
        self.assertEqual([x["id"] for x in open_],["o3"])

    def test_one_line_anchor_rejects_wrong_topic_and_recovers_correct_quote(self):
        approach=("[S1] Full uniqueness game lets an adversary choose PK. "
                  "[S2] Trusted uniqueness game gives the adversary SK. "
                  "[S3] Full pseudorandomness game gives an output without proof.")
        correct="Full pseudorandomness game gives an output without proof."
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p2:c3",1,correct,"command"))
        logs=[]
        fake=SimpleNamespace(
            ledger=ledger,_definition_context_by_claim={},
            warnings=[],extra_obligations=[],
            events=SimpleNamespace(record=lambda event,**kwargs:
                                   logs.append((event,kwargs))))
        p={"approach":approach,"claim_ids":["p2:c3"],"id":"p2"}
        wrong={
            "claims":[{"id":"c3","statement":correct,"sentence_ids":[1],
                        "source_span":"Full uniqueness game lets an adversary choose PK.",
                        "assumptions":[]}]
        }
        FullCouncilRunner._anchors(fake,p,wrong)
        self.assertEqual(p["claim_sentence_ids"]["p2:c3"],[])
        self.assertTrue(any(event=="anchor_topic_mismatch" for event,_ in logs))
        self.assertNotIn("p2:c3",fake._definition_context_by_claim)
        # Even with the *wrong* numeric [S1] ID, an exact source_span can
        # recover the true topic's [S3] provenance.
        fake.ledger=ClaimLedger()
        fake.ledger.add_claim(Claim("p2:c3",1,correct,"command"))
        p={"approach":approach,"claim_ids":["p2:c3"],"id":"p2"}
        right={"claims":[{"id":"c3","statement":correct,"sentence_ids":[1],
                          "source_span":correct,"assumptions":[]}]}
        FullCouncilRunner._anchors(fake,p,right)
        self.assertEqual(p["claim_sentence_ids"]["p2:c3"],[3])
        self.assertEqual(fake._definition_context_by_claim["p2:c3"][1],"3.4")

    def test_unlabelled_sentence_inherits_wrong_game_scope(self):
        # S2 says nothing about "full uniqueness", but its context is S1.
        approach=("[S1] Full uniqueness security game: adversary chooses PK. "
                  "[S2] The adversary outputs two different valid proofs. "
                  "[S3] Trusted uniqueness gives both honestly generated keys.")
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p2:c2",1,
            "Trusted uniqueness requires honest keys given to the adversary.",
            "command"))
        events=[]
        fake=SimpleNamespace(
            ledger=ledger,_definition_context_by_claim={},
            warnings=[],extra_obligations=[],
            events=SimpleNamespace(record=lambda name,**kwargs:
                                   events.append((name,kwargs))))
        p={"approach":approach,"claim_ids":["p2:c2"],"id":"p2"}
        raw={"claims":[{"id":"c2",
                        "statement":ledger.claims["p2:c2"].statement,
                        "source_span":"The adversary outputs two different valid proofs.",
                        "sentence_ids":[2],"assumptions":[]}]}
        FullCouncilRunner._anchors(fake,p,raw)
        self.assertEqual(p["claim_sentence_ids"]["p2:c2"],[])
        self.assertIsNone(fake.ledger.claims["p2:c2"].source_span)
        self.assertTrue(any(name=="anchor_topic_mismatch" for name,_ in events))

    def test_pure_definition_question_skips_translator_even_for_repairs(self):
        self.assertTrue(is_vrf_definition_question(Q))
        self.assertFalse(is_vrf_definition_question(
            "Prove a lattice VRF construction meets the security games."))
        logs=[]
        async def no_call(*args,**kwargs):
            raise AssertionError("GLM translator must not run")
        fake=SimpleNamespace(
            requirements=None,_current_question=Q,
            ledger=ClaimLedger(),paper_index=None,
            reference_checks=[],extra_obligations=[],
            events=SimpleNamespace(record=lambda event,**kw:
                                   logs.append((event,kw))),
            _call=no_call)
        claim=Claim("p1:c3:repair",1,
            "Full pseudorandomness game returns output without challenge proof.",
            "gpt-oss")
        asyncio.run(FullCouncilRunner._translate_and_check(fake,claim))
        self.assertTrue(any(e=="translator_skipped" for e,_ in logs))
        self.assertTrue(any("semantic alignment" in v
                            for v in fake.extra_obligations))

    def test_gemini_schema_and_validated_objection_judge(self):
        fmt=response_format("Gemini","gemini-3.6-flash","objection_judge")
        self.assertEqual(fmt["type"],"gemini_response_schema")
        self.assertIn("items",fmt["schema"]["properties"])
        result=validate("objection_judge",{"items":[
            {"id":"o17","verdict":"contradicts_reference",
             "quote":"verbatim quote","reason":"SK is allowed"}]})
        self.assertEqual(result["items"][0]["id"],"o17")
        with self.assertRaises(ValueError):
            validate("objection_judge",{"items":[
                {"id":"o3","verdict":"verified","quote":"x"}]})

    def test_grounding_uses_rfc_quote_for_conflict_claim_quote_for_addressed(self):
        ref=("Trusted uniqueness gives honestly generated keys and "
             "reveals SK to the adversary.")
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c2",1,
            "Trusted uniqueness game gives honestly generated SK to the adversary.",
            "gpt-oss"))
        queries=[]
        async def query(family,role,payload,synthesis=False):
            queries.append((family,role))
            return {"items":[
                {"id":"o1","verdict":"contradicts_reference",
                 "quote":"reveals SK to the adversary",
                 "reason":"SK knowledge not a uniqueness break"},
                {"id":"o2","verdict":"already_in_claim",
                 "quote":"gives honestly generated SK to the adversary",
                 "reason":"Claim already says this"},
                {"id":"o3","verdict":"contradicts_reference",
                 "quote":"nonexistent source assertion",
                 "reason":"Hallucinated quote"},
                {"id":"o4","verdict":"contradicts_reference",
                 "quote":"gives honestly generated SK to the adversary",
                 "reason":"Claim quote cannot ground RFC contradiction"}]}
        logs=[]
        state=SimpleNamespace(
            ledger=ledger,judge_family="gemini",
            budget=SimpleNamespace(debate_remaining=lambda:100),
            _call=query,
            events=SimpleNamespace(record=lambda event,**kwargs:
                                   logs.append((event,kwargs))))
        objections=[Objection(f"o{i}","p1","p1:c2","nemotron",
                             "Issue", "Effect","Check") for i in range(1,5)]
        decisions=asyncio.run(FullCouncilRunner._ground_objections(
            state,{"3.3":{"section":"3.3","excerpt":ref,"truncated":False}},
            objections))
        self.assertEqual(queries,[("gemini","objection_judge")])
        self.assertEqual(decisions["o1"]["verdict"],"contradicts_reference")
        self.assertEqual(decisions["o2"]["verdict"],"already_in_claim")
        self.assertEqual(decisions["o3"]["verdict"],"valid")
        self.assertEqual(decisions["o4"]["verdict"],"valid")
        self.assertFalse(decisions["o3"]["grounded"])


if __name__=="__main__":
    unittest.main()
