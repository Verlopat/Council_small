"""Typed claim-thread speech acts. This protocol does not grant models state-write rights."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum

class Act(str, Enum):
    PROPOSE = "PROPOSE"
    CHALLENGE = "CHALLENGE"
    REQUEST_EVIDENCE = "REQUEST_EVIDENCE"
    DEFEND = "DEFEND"
    CONCEDE = "CONCEDE"
    WITHDRAW = "WITHDRAW"
    REPAIR = "REPAIR"
    ASK = "ASK"
    ANSWER = "ANSWER"
    VERIFY_REQUEST = "VERIFY_REQUEST"
    RESULT = "RESULT"
    ABSTAIN = "ABSTAIN"

@dataclass(frozen=True)
class Message:
    id: str
    thread: str
    act: Act
    sender: str
    sender_family: str
    body: str
    evidence: tuple[str, ...] = ()
    to: str | None = None
    reply_to: str | None = None
    round: int = 0
    step_ref: str | None = None

    def __post_init__(self):
        if not self.id or not self.thread or not self.sender or not self.sender_family:
            raise ValueError("Every act requires an ID, thread, sender, and family")
        if self.round < 0:
            raise ValueError("Negative round")
        if not isinstance(self.act, Act):
            raise ValueError("Unknown speech act")
        if len(self.body) > 3200:
            raise ValueError("Message exceeds approximately 600-token cap")
