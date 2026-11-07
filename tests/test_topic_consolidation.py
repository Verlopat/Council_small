"""No API quota needed: check RFC topic judgments and objection triage."""
import unittest
import asyncio
from types import SimpleNamespace
from council.judge import TOPIC_SECTIONS, normalize_topic_judgment
from council.claim_filter import close_to_owner
from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger, ClaimStatus
from council.vrf_audit import (classify_objections, objection_conflicts,
                               scan_audit_issues, partition_addressed_objections)
from council.families import endpoint_list
from council.vrf_sanity import scan_vrf_games
from council.extract import numbered_sentence_excerpt
from council.schemas import validate

QUESTION="Explain VRF full uniqueness, trusted uniqueness and pseudorandomness."


class ConsolidationTests(unittest.TestCase):
    def test_topic_mapping(self):
        self.assertEqual({k:v[1] for k,v in TOPIC_SECTIONS.items()}, {
            "full_uniqueness":"3.1",
            "trusted_uniqueness":"3.3",
            "pseudorandomness":"3.4",
        })

    def test_valid_advisory_judgment_never_verifies(self):
        ref={"section":"3.1","excerpt":"Full uniqueness requires different VRF outputs.",
             "truncated":False}
        versions=[{"id":"p3:c1","statement":"The outputs differ.","flags":[]}]
        reply=validate("topic_judge",{
            "topic":"full_uniqueness",
            "versions":[{"id":"p3:c1","status":"matches",
                          "reference_quote":"different VRF outputs",
                          "reason":"The claim matches the output requirement."}],
            "best_version_id":"p3:c1","missing":["malicious public key choice"],
            "summary":"Different valid outputs must be impossible."})
        result=normalize_topic_judgment("full_uniqueness",ref,versions,reply)
        self.assertEqual(result["best_version_id"],"p3:c1")
        self.assertFalse(result["verified"])
        self.assertEqual(result["versions"][0]["status"],"matches")

    def test_fabricated_quote_not_accepted(self):
        ref={"section":"3.3","excerpt":"the adversary knows the secret key",
             "truncated":False}
        versions=[{"id":"p1:c2","statement":"Trusted uniqueness hides SK.","flags":[]}]
        reply={"topic":"trusted_uniqueness","versions":[
            {"id":"p1:c2","status":"matches",
             "reference_quote":"the secret key is hidden",
             "reason":"Model claim"}],
             "best_version_id":"p1:c2","summary":"Incorrect answer","missing":[]}
        result=normalize_topic_judgment("trusted_uniqueness",ref,versions,reply)
        self.assertEqual(result["versions"][0]["status"],"incomplete")

    def test_truncated_source_blocks_selection(self):
        ref={"section":"3.4","excerpt":"VRF challenge output", "truncated":True}
        versions=[{"id":"p3:c3","statement":"VRF challenge output","flags":[]}]
        result=normalize_topic_judgment("pseudorandomness",ref,versions,{
            "best_version_id":"p3:c3","summary":"This is incomplete",
            "versions":[{"id":"p3:c3","status":"matches",
                         "reference_quote":"VRF challenge output",
                         "reason":"Located"}], "missing":[]})
        self.assertIsNone(result["best_version_id"])
        self.assertFalse(result["reference_complete"])

    def test_rfc_conflicting_review_separated(self):
        obs=[{"id":"o1","source":"reviewer","issue":
             "Trusted uniqueness adversary lacks the secret key SK."},
             {"id":"o2","source":"auditor","issue":
              "Pseudorandomness: without a proof the adversary can trivially "
              "distinguish the real challenge from random."},
             {"id":"o3","source":"reviewer","issue":
              "The pseudorandomness game does not specify a fresh challenge."}]
        flagged,remaining=classify_objections(QUESTION,obs)
        self.assertEqual([x["id"] for x in flagged],["o1","o2"])
        self.assertEqual([x["id"] for x in remaining],["o3"])
        self.assertEqual(len(flagged)+len(remaining),len(obs))

    def test_quoted_criticism_is_not_suppressed(self):
        issue=("The proposal incorrectly assumes trusted uniqueness "
               "adversary lacks the secret key.")
        self.assertFalse(objection_conflicts(QUESTION,"o4",issue))

    def test_one_line_provenance(self):
        answer=("[S1] Full uniqueness allows any key. "
                "[S2] Trusted uniqueness uses honestly generated keys. "
                "[S3] Pseudorandomness has a fresh target.")
        self.assertEqual(numbered_sentence_excerpt(answer,[2]),
                         "Trusted uniqueness uses honestly generated keys.")
        self.assertIn("Pseudorandomness",numbered_sentence_excerpt(answer,[2,3]))
        self.assertNotIn("[S1]",numbered_sentence_excerpt(answer,[2]))

    def test_advantage_flag(self):
        stmt=("In pseudorandomness, advantage is Pr[A wins | b=0] "
              "- Pr[A wins | b=1].")
        flags=scan_vrf_games(QUESTION,[SimpleNamespace(id="p1:c4",statement=stmt)])
        kinds={v["kind"] for v in flags}
        self.assertIn("advantage_on_win",kinds)
        self.assertNotIn("pseudorandomness_oracle_unspecified",kinds)

    def test_advantage_formula_not_missing_oracle(self):
        stmt=("In the pseudorandomness game, advantage equals "
              "|Pr[b'=1|b=0] - Pr[b'=1|b=1]|.")
        flags=scan_vrf_games(QUESTION,[SimpleNamespace(id="p1:c4",statement=stmt)])
        kinds={v["kind"] for v in flags}
        self.assertNotIn("pseudorandomness_oracle_unspecified",kinds)
        self.assertNotIn("pseudorandomness_freshness_unspecified",kinds)


    def test_full_runner_dispatches_all_three_games(self):
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,"Full uniqueness checks distinct outputs.","gpt-oss"))
        ledger.add_claim(Claim("p2:c1",1,"Trusted uniqueness assumes honest keys.","command"))
        ledger.add_claim(Claim("p3:c1",1,"Pseudorandomness challenge reveals only an output.","nemotron"))
        calls=[]
        async def fake_call(family,role,payload,*,synthesis=False):
            calls.append((role,payload["topic"],payload["section"],synthesis))
            return {"topic":payload["topic"],
                    "versions":[{"id":v["id"],"status":"matches",
                                 "reference_quote":"A matched reference",
                                 "reason":"Matches the supplied words."}
                                for v in payload["versions"]],
                    "best_version_id":payload["versions"][0]["id"],
                    "missing":[],"summary":"An advisory comparison."}
        state=SimpleNamespace(
            ledger=ledger,paper_index=SimpleNamespace(
                rfc_section_excerpt=lambda section,max_chars:
                {"section":section,"excerpt":"A matched reference",
                 "truncated":False}),
            judge_family="gemini",
            budget=SimpleNamespace(debate_remaining=lambda:100),
            events=SimpleNamespace(record=lambda *a,**k:None),
            _call=fake_call)
        results=asyncio.run(FullCouncilRunner._consolidate_topics(
            state,QUESTION,[]))
        self.assertEqual(len(results),3)
        self.assertEqual([call[0] for call in calls],["topic_judge"]*3)
        self.assertEqual([call[2] for call in calls],["3.1","3.3","3.4"])
        self.assertTrue(all(result["best_version_id"] for result in results))
        self.assertTrue(all(claim.status==ClaimStatus.PROPOSED
                            for claim in ledger.claims.values()))

    def test_near_identical_opposite_negations_are_not_deduplicated(self):
        owner=SimpleNamespace(
            id="p1:c2",statement="Trusted uniqueness allows knowledge "
            "of the secret key for honestly generated keys.")
        rival="Trusted uniqueness does not allow knowledge of the secret key for honestly generated keys."
        self.assertIsNone(close_to_owner(rival,[owner],threshold=0.85))

    def test_objection_topic_from_target_claim(self):
        suspects=[{"id":"o1","source":"reviewer","topic":"2_trusted_uniqueness",
                   "issue":"The adversary lacks the secret key."}]
        flagged,others=classify_objections(QUESTION,suspects)
        self.assertEqual([row["id"] for row in flagged],["o1"])
        self.assertFalse(others)


    def test_inline_s2_warning_is_not_attached_to_s1(self):
        approach=("[S1] Define three security games. "
                  "[S2] Trusted uniqueness requires that the adversary "
                  "never learns the secret key SK. "
                  "[S3] Full uniqueness permits malicious public keys.")
        state=SimpleNamespace(ledger=ClaimLedger())
        warnings=FullCouncilRunner._vrf_findings(
            state, QUESTION, [{"id":"p2","approach":approach,"claim_ids":[]}])
        found=[r for r in warnings
               if r["kind"]=="trusted_uniqueness_sk_secrecy_contradiction"]
        self.assertEqual([r["claim_id"] for r in found],["p2:approach:S2"])


    def test_wrapped_rfc_quote_is_grounded(self):
        ref={"section":"3.1",
             "excerpt":"One public key and a common input,\\n"
                       "   but two different outputs are forbidden.",
             "truncated":False}
        versions=[{"id":"p3:c1","statement":"No two different outputs.","flags":[]}]
        verdict={"topic":"full_uniqueness",
                 "versions":[{"id":"p3:c1","status":"matches",
                     "reference_quote":"a common input, but two different outputs",
                     "reason":"Same property"}],
                 "best_version_id":"p3:c1","summary":"Two different outputs forbidden",
                 "missing":[]}
        fixed=normalize_topic_judgment("full_uniqueness",ref,versions,verdict)
        self.assertEqual(fixed["best_version_id"],"p3:c1")
        self.assertTrue(fixed["versions"][0]["quote_grounded"])
        self.assertFalse(fixed["verified"])

    def test_soft_hyphen_in_rfc_does_not_invalidate_quote(self):
        ref={"section":"3.4","excerpt":"pseudo\u00adrandom challenge output",
             "truncated":False}
        reply={"versions":[{"id":"p3:c3","status":"matches",
                 "reference_quote":"pseudorandom challenge output",
                 "reason":"Source text"}],"best_version_id":"p3:c3",
               "summary":"Pseudorandomness","missing":[]}
        versions=[{"id":"p3:c3","statement":"Pseudorandom challenge output.","flags":[]}]
        fixed=normalize_topic_judgment("pseudorandomness",ref,versions,reply)
        self.assertEqual(fixed["best_version_id"],"p3:c3")

    def test_none_selected_explains_partial_matches(self):
        ref={"section":"3.3",
             "excerpt":"Honest keys, adversary learns the secret key, and "
                       "two distinct accepted outputs for one input.",
             "truncated":False}
        versions=[{"id":"p1:c2","statement":"SK given, wrong win condition","flags":[]},
                  {"id":"p3:c2","statement":"SK withheld, right win condition","flags":[]}]
        reply={"versions":[
            {"id":"p1:c2","status":"incomplete",
             "reference_quote":"adversary learns the secret key",
             "reason":"Wrong output condition"},
            {"id":"p3:c2","status":"contradicts",
             "reference_quote":"two distinct accepted outputs for one input",
             "reason":"SK withheld"}],"best_version_id":None,
            "missing":["combine the source-aligned requirements"],
            "summary":"Neither version matches §3.3.",
            "partial_matches":[
                {"id":"p1:c2","agrees":["secret key is given"],
                 "conflicts":["wrong win condition"],
                 "reference_quote":"adversary learns the secret key"},
                {"id":"p3:c2","agrees":["right two-output win condition"],
                 "conflicts":["secret key withheld"],
                 "reference_quote":"two distinct accepted outputs for one input"},
                {"id":"p9:c9","agrees":["invented"],"conflicts":[],
                 "reference_quote":"invented"}]}
        result=normalize_topic_judgment("trusted_uniqueness",ref,versions,reply)
        self.assertIsNone(result["best_version_id"])
        self.assertEqual([m["id"] for m in result["partial_matches"]],
                         ["p1:c2","p3:c2"])
        self.assertFalse(result["verified"])

    def test_audit3_correct_no_challenge_proof_not_flagged(self):
        issue=("p1:c3 describes the pseudorandomness game as providing a "
               "simulated proof in the random case (b=1). In standard VRF "
               "security definitions, the challenge output must be provided "
               "WITHOUT a proof, as the ability to verify the output would "
               "trivially distinguish it from a random value.")
        rows=objection_conflicts(QUESTION,"audit:3",issue)
        self.assertEqual(rows,[])
        self.assertFalse(any(
            r["kind"]=="auditor_challenge_proof_scope_confusion"
            for r in scan_audit_issues(QUESTION,[issue])))
        flagged,regular=classify_objections(QUESTION,[
            {"id":"audit:3","source":"auditor","issue":issue}])
        self.assertEqual(flagged,[])
        self.assertEqual(len(regular),1)

    def test_objection_already_addressed_requires_post_challenge_rule(self):
        objection={"id":"o3","source":"reviewer",
                   "topic":"3_pseudorandomness",
                   "issue":"The game does not stop the adversary from later "
                           "querying Eval on x* for a proof.",
                   "target_text":"x* not previously queried; the adversary "
                                 "is forbidden from querying Eval on x* after "
                                 "the challenge."}
        addressed,open_items=partition_addressed_objections([objection])
        self.assertEqual([r["id"] for r in addressed],["o3"])
        self.assertEqual(open_items,[])
        self.assertEqual(addressed[0]["advisory_status"],
                         "already_addressed_by_claim")
        self.assertNotIn("target_text",addressed[0])

    def test_prechallenge_only_is_not_sufficient(self):
        objection={"id":"o3","source":"reviewer",
                   "topic":"3_pseudorandomness",
                   "issue":"It does not forbid the adversary from later "
                           "querying Eval on x* after the challenge.",
                   "target_text":"Adversary chooses x* not previously queried."}
        addressed,open_items=partition_addressed_objections([objection])
        self.assertEqual(addressed,[])
        self.assertEqual(len(open_items),1)

    def test_uniqueness_beta_outputs_is_not_proof_only(self):
        claim=("Full uniqueness: adversary supplies two distinct proofs "
               "π₁, π₂ that both verify on one input, with distinct outputs "
               "β₁ ≠ β₂.")
        warnings=scan_vrf_games(QUESTION,[
            SimpleNamespace(id="p3:c1:repair",statement=claim)])
        self.assertNotIn("uniqueness_on_proofs",
                         {r["kind"] for r in warnings})

    def test_reviewer_payload_does_not_duplicate_full_proposal(self):
        ledger=ClaimLedger()
        claim=Claim("p3:c3",1,
            "Pseudorandomness oracle has a fresh challenge.","nemotron")
        claim.source_span="The challenger chooses x* with no prior queries."
        ledger.add_claim(claim)
        state=SimpleNamespace(ledger=ledger,objections=[])
        p={"id":"p3","claim_ids":["p3:c3"],"approach":"very long full proposal"}
        result=FullCouncilRunner._review_payload(state,QUESTION,p)
        self.assertNotIn("approach",str(result))
        self.assertEqual(result["claims"][0]["cited_sentence"],claim.source_span)
        self.assertEqual(result["claims"][0]["id"],"p3:c3")

    def test_nemotron_and_command_max_tokens_all_roles(self):
        self.assertTrue(all(x.max_tokens>=8000 for x in endpoint_list("nemotron")))
        self.assertTrue(all(x.max_tokens>=4000 for x in endpoint_list("command")))


if __name__ == "__main__":
    unittest.main()
