"""Reproducible SQLite response cache keyed by complete generation identity."""
from __future__ import annotations
from pathlib import Path
import json
import sqlite3
from council.cache_key import response_cache_key

class ResponseCache:
    def __init__(self, path: Path):
        self.db = sqlite3.connect(path)
        self.db.execute("""CREATE TABLE IF NOT EXISTS responses
            (key TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT NOT NULL,
             sample_id TEXT NOT NULL, payload TEXT NOT NULL)""")
        self.db.commit()

    def get(self, *, provider: str, model: str, messages: list[dict], settings: dict,
            prompt_version: str, sample_id: str):
        key = response_cache_key(provider=provider, model=model, messages=messages,
                                 settings=settings, prompt_version=prompt_version,
                                 sample_id=sample_id)
        row = self.db.execute("SELECT payload FROM responses WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, payload: dict, *, provider: str, model: str, messages: list[dict],
            settings: dict, prompt_version: str, sample_id: str):
        key = response_cache_key(provider=provider, model=model, messages=messages,
                                 settings=settings, prompt_version=prompt_version,
                                 sample_id=sample_id)
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO responses VALUES (?,?,?,?,?)",
                            (key, provider, model, sample_id,
                             json.dumps(payload, ensure_ascii=False)))
        return key

    def close(self):
        self.db.close()
