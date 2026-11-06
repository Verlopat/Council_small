"""No API quota needed: check RFC topic judgments and objection triage."""
import unittest
from types import SimpleNamespace
from council.judge import TOPIC_SECTIONS, normalize_topic_judgment
from council.vrf_audit import classify_objections, objection_conflicts
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
              "Pseudorandomness: without proof the challenger is trivially "
              "distinguishable."},
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


if __name__ == "__main__":
    unittest.main()
