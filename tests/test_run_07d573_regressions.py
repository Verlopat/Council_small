"""Regression cases from the 07d573b4f7c84ec5 VRF Council run.

All tests are offline: no paid/free provider requests and no local user data.
"""
import asyncio
import unittest
from types import SimpleNamespace

from council.definition_sources import classify, game_step
from council.extract import source_sentence_ids
from council.families import endpoint_list
from council.full import FullCouncilRunner
from council.judge import normalize_topic_judgment
from council.models import Claim, ClaimLedger
from council.schemas import validate
from council.structured import response_format
from council.vrf_audit import (
    objection_conflicts, partition_addressed_objections,
    deduplicate_objections,
)
from council.workflow import CouncilRunner

QUESTION="Explain full uniqueness, trusted uniqueness and pseudorandomness security games for a lattice-based VRF."


class RecentRunRegressionTests(unittest.TestCase):
    def test_gemini_topic_judge_can_omit_known_fields(self):
        obj=validate("topic_judge",{
            "versions":[{"id":"p1:c1:repair","status":"matches",
                         "reference_quote":"two different outputs",
                         "reason":"Matches output criterion."}],
            "best_version_id":"p1:c1:repair"})
        self.assertNotIn("topic",obj)
        self.assertNotIn("summary",obj)
        ref={"section":"3.1","excerpt":"No two different outputs verify.",
             "truncated":False}
        result=normalize_topic_judgment("full_uniqueness",ref,
            [{"id":"p1:c1:repair","statement":"No two outputs verify.","flags":[]}],
            obj)
        self.assertEqual(result["best_version_id"],"p1:c1:repair")
        self.assertFalse(result["verified"])

    def test_topic_judge_gemini_schema(self):
        fmt=response_format("Gemini","gemini-3.6-flash","topic_judge")
        self.assertEqual(fmt["type"],"gemini_response_schema")
        schema=fmt["schema"]
        self.assertEqual(schema["type"],"OBJECT")
        self.assertEqual(schema["required"],["versions"])
        self.assertIn("versions",schema["properties"])
        self.assertNotIn("summary",schema["required"])

    def test_topic_judge_format_retry(self):
        seen=[]
        class DummyTransport:
            async def complete(self,family,message,budget,*,role,synthesis):
                seen.append(message)
                text= "{" if len(seen)==1 else (
                    '{"versions":[{"id":"p1:c1:repair",'
                    '"status":"matches","reason":"Citation",'
                    '"reference_quote":"two outputs"}],'
                    '"best_version_id":"p1:c1:repair"}')
                return SimpleNamespace(text=text,provider="Gemini",
                                       model="gemini-3.6-flash",
                                       prompt_hash="hash")
        class Events:
            def record(self,*args,**kwargs):
                pass
        fake=SimpleNamespace(
            transport=DummyTransport(),budget=SimpleNamespace(
                allowed=lambda *args,**kwargs:100),
            warnings=[],actual_models=[],events=Events())
        result=asyncio.run(CouncilRunner._call(fake,"gemini","topic_judge",
            {"topic":"full_uniqueness","versions":[]}))
        self.assertIsNotNone(result)
        self.assertEqual(len(seen),2)
        self.assertIn("FORMAT RETRY",seen[1])
        self.assertFalse(fake.warnings)

    def test_all_role_string_list_coercion(self):
        revised=validate("revision",{
            "revised_claims":[{"claim_id":"p1:c1",
                "statement":"Full uniqueness fixes one input.",
                "assumptions":"malicious pk allowed"}],
            "responses":[]})
        self.assertEqual(revised["revised_claims"][0]["assumptions"],
                         ["malicious pk allowed"])
        hunter=validate("hunter",{"found":False,"tried":"one calculation"})
        self.assertEqual(hunter["tried"],["one calculation"])
        audit=validate("audit",{"issues":"issue A",
                                "suggested_checks":"check B"})
        self.assertEqual(audit["issues"],["issue A"])
        judge=validate("topic_judge",{
            "versions":[],"missing":"challenge input freshness"})
        self.assertEqual(judge["missing"],["challenge input freshness"])

    def test_wrong_typed_sentence_ids_still_rejected(self):
        with self.assertRaises(ValueError):
            validate("proposal",{"approach":"[S1] Definition.",
                "claims":[{"id":"c1","statement":"Full uniqueness game.",
                           "sentence_ids":"1,2"}]})

    def test_no_proof_misconception_o8_and_o12(self):
        items=[
            "The pseudorandomness game omits the proof π* from the challenge "
            "response, yet verification of y* may be possible using the "
            "public key; the adversary could detect the absence of a valid "
            "proof and distinguish the real output from random.",
            "The challenge response omits the proof π* while the verification "
            "algorithm may detect the absence of a valid proof, giving the "
            "adversary a distinguishing advantage unrelated to pseudorandomness."]
        for i,issue in enumerate(items,8):
            with self.subTest(issue=i):
                kinds={x["kind"] for x in objection_conflicts(
                    QUESTION,"o"+str(i),issue,"3_pseudorandomness")}
                self.assertIn("contradicts_rfc_3_4_no_challenge_proof",kinds)

    def test_correct_audit3_remains_unflagged(self):
        issue=("The challenge output must be provided WITHOUT a proof, "
               "as the ability to verify the output would trivially "
               "distinguish it from a random value.")
        kinds={x["kind"] for x in objection_conflicts(
            QUESTION,"audit:3",issue,"3_pseudorandomness")}
        self.assertNotIn("contradicts_rfc_3_4_no_challenge_proof",kinds)

    def test_wrong_sk_objections_audit5_o7_o11(self):
        items=[
            "p3:c4 and p3:c5 suggest that the secret key may be revealed "
            "to the adversary, which typically contradicts the purpose "
            "of a VRF uniqueness game, or creates a trivial win if the "
            "VRF is not deterministic.",
            "The trusted uniqueness game mentions that the secret key may "
            "be revealed after some queries but does not forbid the "
            "adversary from using that secret key to compute the VRF "
            "directly on the challenge input, which trivially breaks uniqueness.",
            "The game allows the secret key to be revealed after some "
            "queries but does not forbid the adversary from using that "
            "secret key to compute the VRF on the challenge input, "
            "which trivially yields two distinct outputs."]
        for i,issue in enumerate(items):
            with self.subTest(index=i):
                kinds={v["kind"] for v in objection_conflicts(
                    QUESTION,"audit5-o"+str(i),issue,"2_trusted_uniqueness")}
                self.assertIn("contradicts_rfc_3_3_sk_known",kinds)

    def test_false_already_addressed_does_not_hide_o4(self):
        objection={"id":"o4","source":"reviewer",
                   "topic":"2_trusted_uniqueness",
                   "issue":"The games are identical. The secret key is never "
                           "revealed to the adversary in either one.",
                   "target_statement":"Trusted uniqueness assumes honest key "
                                      "generation and gives only pk to the "
                                      "adversary; secret key is never revealed."}
        flagged,open_items=partition_addressed_objections([objection])
        self.assertFalse(flagged)
        self.assertEqual([v["id"] for v in open_items],["o4"])

    def test_positive_grant_can_address_missing_sk(self):
        objection={"id":"o2","source":"reviewer",
                   "topic":"2_trusted_uniqueness",
                   "issue":"The claim does not give the adversary secret key sk.",
                   "target_statement":"Trusted uniqueness gives both pk and sk "
                                      "to the adversary after honest keygen."}
        flagged,other=partition_addressed_objections([objection])
        self.assertEqual([x["id"] for x in flagged],["o2"])
        self.assertFalse(other)

    def test_malformed_public_key_is_in_full_uniqueness_scope(self):
        objection={"id":"o5","source":"reviewer",
                   "topic":"1_full_uniqueness",
                   "issue":"A malformed public key might make verification "
                           "accept any output, so the definition is missing "
                           "a restriction.",
                   "target_statement":"Full uniqueness permits a public key "
                                      "(possibly maliciously generated) and "
                                      "rules out two distinct accepted outputs."}
        flagged,open_items=partition_addressed_objections([objection])
        self.assertEqual(len(flagged),1)
        self.assertEqual(flagged[0]["matched_requirement"],
                         "malformed_pk_is_covered_by_full_uniqueness")
        self.assertFalse(open_items)

    def test_similar_objections_collapsed_but_ids_retained(self):
        items=[
            {"id":"o5","topic":"1_full_uniqueness",
             "issue":"A malformed public key makes verification accept any output."},
            {"id":"o9","topic":"1_full_uniqueness",
             "issue":"Malformed pk may cause the verifier to accept arbitrary outputs."},
            {"id":"o7","topic":"2_trusted_uniqueness",
             "issue":"Revealed secret key lets adversary compute VRF and trivially "
                     "break uniqueness."},
            {"id":"o11","topic":"2_trusted_uniqueness",
             "issue":"An attacker may use the known secret key to compute the VRF "
                     "and trivially break uniqueness."},
            {"id":"o8","topic":"3_pseudorandomness",
             "issue":"Challenge omits its proof, allowing an adversary to "
                     "distinguish outputs."},
            {"id":"o12","topic":"3_pseudorandomness",
             "issue":"Omission of the challenge proof can distinguish the output."}]
        unique=deduplicate_objections(items)
        self.assertEqual(len(unique),3)
        self.assertEqual([x["duplicate_ids"] for x in unique],
                         [["o9"],["o11"],["o12"]])
        self.assertEqual(len(items),6)

    def test_trusted_contrast_always_routes_section_3_3(self):
        route=classify(QUESTION,
            "Trusted uniqueness uses honestly generated keys; unlike "
            "full uniqueness, which allows malicious keys.")
        self.assertEqual(route[1],"3.3")
        route=classify(QUESTION,
            "The full uniqueness game is contrasted with trusted uniqueness "
            "which gives sk to the adversary.")
        self.assertEqual(route[1],"3.3")

    def test_unlabelled_game_steps_skip_translator(self):
        for statement in (
            "The challenger generates a key pair and gives pk to the adversary.",
            "The adversary wins if two outputs verify under pk.",
            "The adversary can query an evaluation oracle."):
            self.assertTrue(game_step(QUESTION,statement))
            claim=Claim("p3:c2",1,statement,"nemotron")
            calls=[]
            async def should_not_call(*a,**k):
                calls.append(a)
                raise AssertionError("generic VRF step must not call GLM")
            class Events:
                def record(self,*args,**kwargs):
                    pass
            state=SimpleNamespace(
                requirements=None,_current_question=QUESTION,ledger=ClaimLedger(),
                _definition_context_by_claim={},events=Events(),
                extra_obligations=[],reference_checks=[],paper_index=None,
                _call=should_not_call)
            asyncio.run(FullCouncilRunner._translate_and_check(state,claim))
            self.assertEqual(calls,[])
            self.assertIn("game-step definition",
                          state.extra_obligations[-1])

    def test_rival_sentence_coverage_suppresses_reextraction(self):
        approach=("[S1] Full uniqueness is adversarially secure. "
                  "The challenger generates a key pair. "
                  "Two distinct outputs must not verify. "
                  "[S2] Trusted uniqueness assumes an honest key.")
        self.assertEqual(
            source_sentence_ids(approach,"The challenger generates a key pair."),
            [1])
        ledger=ClaimLedger()
        cid="p1:c1"
        ledger.add_claim(Claim(cid,1,
            "Full uniqueness requires two different outputs on one input.",
            "gpt-oss"))
        owner={"id":"p1","approach":approach,"answer":approach,
               "claim_ids":[cid],"claim_map":{"c1":cid},"family":"gpt-oss"}
        record=[]
        state=SimpleNamespace(
            ledger=ledger,warnings=[],extra_obligations=[],
            _definition_context_by_claim={},max_claims=12,
            events=SimpleNamespace(record=lambda *a,**k:record.append((a,k))))
        body={"claims":[{"id":"c1","statement":ledger.claims[cid].statement,
                         "source_span":"Full uniqueness is adversarially secure.",
                         "sentence_ids":[1],"assumptions":[]}]}
        FullCouncilRunner._anchors(state,owner,body)
        self.assertEqual(owner["claim_sentence_ids"][cid],[1])
        async def fake_extract(*a,**kw):
            return {"claims":[{"statement":"The challenger generates a key pair.",
                               "source_span":"The challenger generates a key pair.",
                               "assumptions":[]}]}
        state._call=fake_extract
        asyncio.run(FullCouncilRunner._extract_rival(state,owner,"nemotron"))
        self.assertEqual(len(ledger.claims),1)
        self.assertTrue(any(a[0]=="rival_claim_duplicate_skipped" for a,k in record))

    def test_cohere_larger_and_prompt_capped(self):
        eps=endpoint_list("command")
        self.assertTrue(all(x.max_tokens>=4500 for x in eps))
        from council.prompts import prompt
        self.assertIn("AT MOST SIX",prompt("proposal",{"question":QUESTION}))


if __name__=="__main__":
    unittest.main()
