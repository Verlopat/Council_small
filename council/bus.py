"""Thread-local delivery, immutable raw messages and deterministic dedupe."""
from __future__ import annotations
import hashlib
from collections import defaultdict
from council.protocol import Message

class ThreadBus:
    def __init__(self, max_messages: int = 5, per_pair: int = 3):
        self.messages: dict[str, list[Message]] = defaultdict(list)
        self.seen: dict[str, set[str]] = defaultdict(set)
        self.max_messages = max_messages
        self.per_pair = per_pair

    def deliver(self, msg: Message) -> bool:
        thread = self.messages[msg.thread]
        if len(thread) >= self.max_messages:
            return False
        fingerprint = hashlib.sha256(
            (msg.act.value + "|" + " ".join(msg.body.casefold().split())
             + "|" + ",".join(sorted(msg.evidence))).encode()).hexdigest()
        if fingerprint in self.seen[msg.thread]:
            return False
        # This is a strict exact-normalized dedupe, not unproven semantic equivalence.
        self.seen[msg.thread].add(fingerprint)
        thread.append(msg)
        return True

    def view(self, thread: str, actor: str, *, allowed: set[str]) -> tuple[Message, ...]:
        if actor not in allowed:
            raise PermissionError("Agent is not assigned to this thread")
        return tuple(self.messages.get(thread, ()))
