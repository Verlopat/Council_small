"""Local append-only JSONL + SQLite event log, with deterministic replay."""
from __future__ import annotations
import json
import os
from pathlib import Path
import sqlite3
import time

class EventStore:
    def __init__(self, root: Path, run_id: str):
        if not run_id or "/" in run_id or "\\" in run_id:
            raise ValueError("Invalid run id")
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.root, 0o700)
        self.run_id = run_id
        self.logfile = self.root / (run_id + ".jsonl")
        self.database = self.root / (run_id + ".sqlite3")
        self.db = sqlite3.connect(self.database)
        self.db.execute("""CREATE TABLE IF NOT EXISTS events
                           (seq INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL NOT NULL,
                            event_type TEXT NOT NULL, payload_json TEXT NOT NULL)""")
        self.db.commit()
        os.chmod(self.database, 0o600)

    def record(self, event_type: str, **payload) -> dict:
        if not event_type or not event_type.replace("_", "").isalnum():
            raise ValueError("Invalid event type")
        entry = {"run_id": self.run_id, "timestamp": time.time(),
                 "event": event_type, "payload": payload}
        line = json.dumps(entry, ensure_ascii=False, sort_keys=True)
        # SQLite is authoritative for replay; JSONL is a human-readable mirror.
        with self.db:
            self.db.execute("INSERT INTO events(timestamp,event_type,payload_json) VALUES (?,?,?)",
                            (entry["timestamp"], event_type, json.dumps(payload, ensure_ascii=False)))
        fd = os.open(self.logfile, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            with os.fdopen(fd, "a", encoding="utf-8") as out:
                out.write(line + "\n")
        finally:
            os.chmod(self.logfile, 0o600)
        return entry

    def replay(self) -> list[dict]:
        rows = self.db.execute("SELECT timestamp,event_type,payload_json FROM events ORDER BY seq")
        return [{"run_id": self.run_id, "timestamp": t, "event": kind,
                 "payload": json.loads(data)} for t, kind, data in rows]

    def close(self) -> None:
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
