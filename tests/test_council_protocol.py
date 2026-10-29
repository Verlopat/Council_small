"""Offline protocol regressions for evidence polarity and protected claim state."""
import unittest
from council.models import Claim, ClaimLedger, ClaimStatus, Evidence, EvidenceKind
from council.protocol import Act, Message
from council.evidence import evaluate_polarity, EvidenceRejected
from council.bus import MessageBus, MessageCap
from council.moderator import Moderator

class ProtocolTests(unittest.TestCase):
    def setUp(self):
        self.ledger = ClaimLedger()
        self.ledger.add_claim(Claim("c", 1, "Unproven claim", "gpt-oss"))
        self.ledger.evidence["p"] = Evidence("p","c",1,EvidenceKind.TEST,"pass","test","h",independently_checked=True)
        self.ledger.evidence["f"] = Evidence("f","c",1,EvidenceKind.TEST,"fail","test","h2",independently_checked=True)
        self.ledger.evidence["x"] = Evidence("x","c",1,EvidenceKind.COUNTEREXAMPLE,"fail","attack","h3",independently_checked=True)
    def message(self, act, family="gpt-oss", refs=(), step=None, mid="m"):
        return Message(mid,"c",act,family,family,"body",evidence=refs,step_ref=step)
    def test_conformity_does_not_change_status(self):
        moderator = Moderator(self.ledger)
        self.assertEqual(moderator.submit(self.message(Act.CONCEDE)), "rejected")
        self.assertEqual(self.ledger.claims["c"].status, ClaimStatus.PROPOSED)
    def test_failing_proof_does_not_refute_theorem(self):
        Moderator(self.ledger).submit(self.message(Act.CONCEDE,refs=("f",)))
        self.assertEqual(self.ledger.claims["c"].status, ClaimStatus.UNRESOLVED)
    def test_independently_checked_counterexample(self):
        Moderator(self.ledger).submit(self.message(Act.CONCEDE,refs=("x",)))
        self.assertEqual(self.ledger.claims["c"].status, ClaimStatus.CONTRADICTED)
    def test_wrong_polarity(self):
        self.assertFalse(evaluate_polarity(self.message(Act.CONCEDE,refs=("p",)),
                         self.ledger).acceptable)
    def test_mismatched_claim_version(self):
        self.ledger.revise("c", "New claim")
        with self.assertRaises(EvidenceRejected):
            evaluate_polarity(self.message(Act.DEFEND,refs=("p",)), self.ledger)
    def test_claim_owner_only(self):
        with self.assertRaises(EvidenceRejected):
            evaluate_polarity(self.message(Act.DEFEND, family="command",refs=("p",)),
                              self.ledger)
    def test_untrusted_evidence_ref(self):
        with self.assertRaises(EvidenceRejected):
            evaluate_polarity(self.message(Act.CHALLENGE, family="command",refs=("missing",)),
                              self.ledger)
    def test_unverified_challenge_is_not_refutation(self):
        Moderator(self.ledger).submit(self.message(Act.CHALLENGE, family="command",step="line4"))
        self.assertEqual(self.ledger.claims["c"].status, ClaimStatus.UNRESOLVED)
    def test_round_requires_new_evidence(self):
        mod=Moderator(self.ledger)
        self.assertTrue(mod.begin_next_round())
        self.assertFalse(mod.begin_next_round())
    def test_message_caps(self):
        bus=MessageBus(message_cap=1)
        bus.deliver(self.message(Act.ABSTAIN))
        with self.assertRaises(MessageCap):
            bus.deliver(self.message(Act.ABSTAIN,mid="2"))
    def test_modalities_are_not_stripped(self):
        bus=MessageBus()
        a=self.message(Act.ABSTAIN)
        b=Message("b","c",Act.ABSTAIN,"other","other","other body")
        self.assertNotEqual(bus.fingerprint(a),bus.fingerprint(b))

if __name__=="__main__":
    unittest.main()
