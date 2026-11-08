"""Run 4878d408 regression: the RFC review gate must not corrupt authors.

These are offline orchestration invariants; quote matching is not proof.
"""
import contextlib
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
import unittest

from council.cli import print_compact_result
from council.full import FullCouncilRunner
from council.models import Claim, ClaimLedger, Objection
from council.objection_sections import presentation_sections
from council.plan_sanity import is_plan_instead_of_answer
from council.vrf_audit import objection_conflicts
from council.vrf_sanity import scan_vrf_games, unsupported_full_sk_secrecy


QUESTION=("Explain full uniqueness, trusted uniqueness, and pseudorandomness "
          "security games for a lattice-based VRF.")


def ob(ident,claim="p1:c3",issue="The target can be queried after the challenge"):
    return Objection(ident,"p1",claim,"nemotron",issue,"impact","check RFC")


class ProtectedAuthorReviewTests(unittest.TestCase):
    def test_grounded_valid_overrides_regex_false_positive(self):
        x=ob("o3",issue=(
            "The claim says it gets beta without proof, then must distinguish "
            "the challenge. However it does not specify whether the target "
            "can be queried after the challenge."))
        regex=[{"id":"o3","claim_id":x.claim_id,
                "issue":x.issue,"kinds":["contradicts_rfc_3_4_no_challenge_proof"],
                "reason":"rfc_conflict"}]
        grounded={"o3":{"verdict":"valid","grounded":True,
                        "section":"3.4",
                        "quote":"challenge input must never be queried"}}
        withheld,authors,pending=FullCouncilRunner._screen_revision_objections(
            [x],regex,grounded,require_grounded=True)
        self.assertEqual(withheld,[])
        self.assertEqual([item.id for item in authors],["o3"])
        self.assertEqual(pending,[])

    def test_unjudged_objection_cannot_edit_an_author(self):
        xs=[ob("o1"),ob("o2"),ob("o3")]
        regex=[{"id":"o2","claim_id":"p1:c3","issue":"incorrect",
                "kinds":["contradicts_rfc_3_4_no_challenge_proof"],
                "reason":"rfc_conflict"}]
        grounded={"o1":{"verdict":"unjudged","grounded":False},
                  "o2":{"verdict":"unjudged","grounded":False},
                  "o3":{"verdict":"already_in_claim","grounded":True,
                        "section":"3.4","quote":"the claim forbids this"}}
        withheld,authors,pending=FullCouncilRunner._screen_revision_objections(
            xs,regex,grounded,require_grounded=True)
        self.assertEqual(authors,[])
        self.assertEqual([item["id"] for item in withheld],["o2","o3"])
        self.assertEqual([item["id"] for item in pending],["o1"])
        self.assertEqual(withheld[0]["reason"],"regex_fallback_rfc_conflict")

    def test_non_definition_research_still_allows_peer_review(self):
        x=ob("o1")
        withheld,authors,pending=FullCouncilRunner._screen_revision_objections(
            [x],[],{},require_grounded=False)
        self.assertEqual(withheld,[])
        self.assertEqual([item.id for item in authors],["o1"])
        self.assertEqual(pending,[])

    def test_no_proof_false_positive_does_not_hide_post_challenge_issue(self):
        issue=("The claim states that the adversary receives a challenge beta "
               "for a target alpha (without proof) and must distinguish beta "
               "from a random string. However, it does not specify if the "
               "adversary is allowed to query the evaluation oracle for the "
               "target alpha after receiving the challenge.")
        flags={row["kind"] for row in objection_conflicts(
            QUESTION,"o3",issue,"3_pseudorandomness")}
        self.assertNotIn("contradicts_rfc_3_4_no_challenge_proof",flags)

    def test_auditor_issues_target_existing_claims_not_arbitrary_ids(self):
        ledger=ClaimLedger()
        for cid,name in (
                ("p1:c2","Trusted uniqueness grants SK"),
                ("p3:c3","Full pseudorandomness forbids target queries")):
            ledger.add_claim(Claim(cid,1,name,"nemotron"))
        issues=[
            "Critical error: p1:c2 reveals SK to adversary.",
            "Missing freshness: p3:c3 allows previously queried targets.",
            "One generic audit warning with no claim identifiers.",
            "Unknown ID p8:c999 not in ledger."]
        result=FullCouncilRunner._audit_objection_candidates(
            issues,ledger,"gemma")
        self.assertEqual([(x.id,x.claim_id) for x in result],
                         [("audit:1","p1:c2"),("audit:2","p3:c3")])
        self.assertTrue(all(x.reviewer_family=="gemma" for x in result))

    def test_exclusive_sections_and_grounded_valid_override_regex(self):
        raw=[
            {"id":"o1","source":"reviewer","issue":"Withheld correction"},
            {"id":"o2","source":"reviewer","issue":"Already in the claim"},
            {"id":"o3","source":"reviewer","issue":"Contradicts official RFC"},
            {"id":"o4","source":"reviewer","issue":"Genuine gap"},
            {"id":"o5","source":"reviewer","issue":"Unjudged"},
            {"id":"audit:2","source":"auditor","issue":"SK is forbidden"},
            {"id":"audit:5","source":"auditor","issue":"No prior freshness"}]
        pre=[{"id":"o1","issue":"Withheld correction","reason":"regex_fallback"}]
        verdicts={
            "o1":{"verdict":"already_in_claim","grounded":True},
            "o2":{"verdict":"already_in_claim","grounded":True,"quote":"target text"},
            "o3":{"verdict":"contradicts_reference","grounded":True,"quote":"RFC text"},
            "o4":{"verdict":"valid","grounded":True,"quote":"RFC text"},
            "o5":{"verdict":"unjudged","grounded":False},
            "audit:2":{"verdict":"contradicts_reference","grounded":True},
            "audit:5":{"verdict":"already_in_claim","grounded":True}}
        buckets=presentation_sections(QUESTION,raw,pre,verdicts,
                                      require_grounded=True)
        self.assertEqual([x["id"] for x in buckets["withheld"]],["o1"])
        self.assertEqual([x["id"] for x in buckets["addressed"]],
                         ["o2","audit:5"])
        self.assertEqual([x["id"] for x in buckets["conflicts"]],
                         ["o3","audit:2"])
        self.assertEqual([x["id"] for x in buckets["open"]],["o4"])
        self.assertEqual([x["id"] for x in buckets["unjudged"]],["o5"])
        ids=[x["id"] for values in buckets.values() for x in values]
        self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(set(ids),{x["id"] for x in raw})

    def test_one_sentence_command_outline_retries(self):
        task=("[S1] Define full uniqueness, trusted uniqueness, and "
              "pseudorandomness security games for lattice-based VRFs "
              "based on RFC 9381.")
        self.assertTrue(is_plan_instead_of_answer(QUESTION,task))
        answer=("[S1] Define full uniqueness as a game where the adversary "
                "chooses PK and outputs one input with two valid proofs "
                "yielding beta1 != beta2.")
        self.assertFalse(is_plan_instead_of_answer(QUESTION,answer))

    def test_full_uniqueness_sk_restriction_rejected_and_flagged(self):
        bad=("Full uniqueness game: the adversary chooses PK but is not "
             "given access to any secret key SK and cannot use SK.")
        good=("Full uniqueness game: the adversary chooses PK and may "
              "know SK while producing two different accepted outputs.")
        self.assertTrue(unsupported_full_sk_secrecy(bad))
        self.assertFalse(unsupported_full_sk_secrecy(good))
        warnings=scan_vrf_games(QUESTION,[
            SimpleNamespace(id="p1:repair",statement=bad)])
        self.assertIn("full_uniqueness_invalid_sk_restriction",
                      {x["kind"] for x in warnings})
        ledger=ClaimLedger()
        ledger.add_claim(Claim("p1:c1",1,good,"gpt-oss"))
        events=[]
        state=SimpleNamespace(
            ledger=ledger,requirements=None,_current_question=QUESTION,
            events=SimpleNamespace(record=lambda event,**kwargs:
                                   events.append((event,kwargs))),
            warnings=[])
        FullCouncilRunner._apply_revised_claim(
            state,{"revised_approach":"[R1] "+bad},"p1:c1",bad,
            {"source_span":bad,"sentence_ids":[1],"assumptions":[]})
        self.assertEqual(ledger.claims["p1:c1"].statement,good)
        self.assertTrue(any(k=="unsafe_revision_rejected" for k,_ in events))

    def test_pseudorandomness_adversary_receiving_sk_is_flagged(self):
        bad=("Full pseudorandomness game: after receiving (PK, SK) generated "
             "honestly, the adversary queries an evaluation oracle.")
        good=("Full pseudorandomness game: challenger KeyGen produces (PK, SK), "
              "but adversary receives only PK and can query an oracle.")
        flagged=scan_vrf_games(QUESTION,[
            SimpleNamespace(id="p1:c3",statement=bad),
            SimpleNamespace(id="p3:c3",statement=good)])
        bad_flags={x["kind"] for x in flagged if x["claim_id"]=="p1:c3"}
        good_flags={x["kind"] for x in flagged if x["claim_id"]=="p3:c3"}
        self.assertIn("pseudorandomness_adversary_knows_sk",bad_flags)
        self.assertNotIn("pseudorandomness_adversary_knows_sk",good_flags)

    def test_default_compact_output_retains_answer_and_hides_other_claims(self):
        result={
            "research_result":{
                "completion_status":"partial",
                "proposed_approach":"VERY LONG original solver answer",
                "judge_summary":"RFC-aligned game definitions",
                "unresolved_objections":[]},
            "topic_consolidation":[
                {"topic":"full_uniqueness","section":"3.1",
                 "best_version_id":"p3:c1","summary":"One input, different beta."},
                {"topic":"trusted_uniqueness","section":"3.3",
                 "best_version_id":"p1:c2:repair","summary":"Honest keys; SK known."},
                {"topic":"pseudorandomness","section":"3.4",
                 "best_version_id":"p1:c3:repair","summary":"Fresh target, no proof.",
                 "versions":[{"id":"p3:c3","status":"contradicts"}]}],
            "open_objections":[{"id":"o3","issue":"Freshness missing in source claim"}],
            "unjudged_objections":[{"id":"o1","issue":"No valid quote"}],
            "advisory_findings":[
                {"claim_id":"p1:c2:repair","message":"Selected warning"},
                {"claim_id":"p1:c4","message":"Noise to hide"}],
            "role_coverage":{"valid_proposer_families":["gpt-oss","nemotron"],
                             "requested_solvers":["gpt-oss","command","nemotron"],
                             "independent_audit_completed":True},
            "verdict":{"status":"unresolved","cause":"definition_reference_only"},
            "warnings":[]}
        out=StringIO()
        with contextlib.redirect_stdout(out):
            print_compact_result(result,"runid",Path("runs"))
        text=out.getvalue()
        self.assertIn("p3:c1",text)
        self.assertIn("Honest keys; SK known.",text)
        self.assertIn("Judge summary",text)
        self.assertIn("Freshness missing",text)
        self.assertIn("Selected warning",text)
        self.assertNotIn("Noise to hide",text)
        self.assertNotIn("VERY LONG original solver answer",text)
        self.assertNotIn("Unverified claims and proof obligations",text)
        self.assertIn("runs/runid.sqlite3",text)


if __name__=="__main__":
    unittest.main()
