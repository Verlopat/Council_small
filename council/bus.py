"""Scoped anonymous claim-thread messages, duplication protection, and hard caps."""
from __future__ import annotations
import hashlib
import re
from dataclasses import dataclass, field
from council.protocol import Message, Act

class MessageCap(ValueError):
    pass

@dataclass
class Thread:
    claim_id: str
    messages: list[Message] = field(default_factory=list)
    fingerprints: set[str] = field(default_factory=set)
    verifier_calls: int = 0
    repairs: int = 0
    close_cause: str | None = None
    duplicates: int = 0

class MessageBus:
    STALEMATE_CAUSES = frozenset({
        "no_evidence_possible", "agents_gave_up", "cap_hit", "dedupe_dropped"
    })

    def close(self, claim_id: str, cause: str) -> None:
        if cause not in self.STALEMATE_CAUSES:
            raise ValueError("Unknown stalemate cause")
        thread = self.threads.setdefault(claim_id, Thread(claim_id))
        if thread.close_cause is None:
            thread.close_cause = cause

    def stalemates(self) -> dict[str, str]:
        return {cid: thread.close_cause for cid, thread in self.threads.items()
                if thread.close_cause is not None}

    def __init__(self, *, message_cap: int = 5, verifier_cap: int = 2,
                 repair_cap: int = 1, pair_cap: int = 3):
        self.threads: dict[str, Thread] = {}
        self.message_cap, self.verifier_cap = message_cap, verifier_cap
        self.repair_cap, self.pair_cap = repair_cap, pair_cap
        self.handles: dict[str, str] = {}
    def handle(self, model_identity: str) -> str:
        # Opaque, stable within a run; not a source-identifying model label.
        if model_identity not in self.handles:
            self.handles[model_identity] = "agent-" + str(len(self.handles) + 1)
        return self.handles[model_identity]

    @staticmethod
    def fingerprint(message: Message) -> str:
        # Do not remove hedges or quantifiers ("may" vs "must" is material).
        norm = " ".join(re.sub(r"\s+", " ", message.body).strip().casefold().split())
        return hashlib.sha256((message.act.value + ":" + norm).encode()).hexdigest()

    def deliver(self, msg: Message) -> str:
        thread = self.threads.setdefault(msg.thread, Thread(msg.thread))
        if thread.close_cause:
            raise MessageCap("Thread already closed")
        if len(thread.messages) >= self.message_cap:
            thread.close_cause = "cap_hit"
            raise MessageCap("Message cap reached")
        fingerprint = self.fingerprint(msg)
        if fingerprint in thread.fingerprints:
            thread.duplicates += 1
            if thread.duplicates >= 2:
                self.close(msg.thread, "dedupe_dropped")
            return "duplicate"
        if msg.act is Act.VERIFY_REQUEST:
            if thread.verifier_calls >= self.verifier_cap:
                thread.close_cause = "cap_hit"
                raise MessageCap("Verifier cap reached")
            thread.verifier_calls += 1
        if msg.act is Act.REPAIR:
            if thread.repairs >= self.repair_cap:
                thread.close_cause = "cap_hit"
                raise MessageCap("Repair cap reached")
            thread.repairs += 1
        exchanges = sum(1 for old in thread.messages
                        if old.sender_family == msg.sender_family and old.to == msg.to)
        if exchanges >= self.pair_cap:
            thread.close_cause = "cap_hit"
            raise MessageCap("Pair exchange cap reached")
        thread.messages.append(msg)
        thread.fingerprints.add(fingerprint)
        return "accepted"

    def scoped_view(self, claim_id: str, family: str, active_families: set[str]) -> list[Message]:
        if family not in active_families:
            raise PermissionError("Family is not assigned to claim thread")
        return list(self.threads.get(claim_id, Thread(claim_id)).messages)
