"""Typed debate acts and bounded immutable messages (Architecture v4 §7)."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

class Act(str, Enum):
    PROPOSE="PROPOSE"
    CHALLENGE="CHALLENGE"
    REQUEST_EVIDENCE="REQUEST_EVIDENCE"
    DEFEND="DEFEND"
    CONCEDE="CONCEDE"
    WITHDRAW="WITHDRAW"
    REPAIR="REPAIR"
    ASK="ASK"
    ANSWER="ANSWER"
    VERIFY_REQUEST="VERIFY_REQUEST"
    RESULT="RESULT"
    ABSTAIN="ABSTAIN"

@dataclass(frozen=True)
class Message:
    id: str
    thread: str
    act: Act
    sender: str
    body: str
    evidence: tuple[str, ...] = ()
    recipient: str | None = None
    reply_to: str | None = None
    round: int = 0

    def __post_init__(self):
        if not self.id or not self.thread or not self.sender:
            raise ValueError("Message identity, thread and sender required")
        if len(self.body) > 2400:
            raise ValueError("Message exceeds conservative 2400-character limit")
        if self.round < 0:
            raise ValueError("Invalid round")
