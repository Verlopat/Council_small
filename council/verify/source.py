"""Local literature index: verify quoted passage provenance, NOT entailment/truth."""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import sqlite3
import threading
from pathlib import Path

@dataclass(frozen=True)
class PassageCheck:
    found: bool
    document_id: str
    passage_hash: str | None
    scope: str
    semantic_entailment: str = "unchecked"

class PaperIndex:
    def __init__(self, path: Path):
        # The full verifier executes checks in worker threads. SQLite's
        # default thread affinity would reject an otherwise valid quote read.
        self.lock = threading.RLock()
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute("""CREATE TABLE IF NOT EXISTS papers
            (id TEXT PRIMARY KEY, title TEXT NOT NULL, license TEXT NOT NULL,
             source_uri TEXT, content TEXT NOT NULL, content_hash TEXT NOT NULL)""")
        self.db.commit()

    def add(self, document_id: str, title: str, content: str,
            *, license: str, source_uri: str = ""):
        if not document_id or not license or not title or not content:
            raise ValueError("Document metadata, license and text required")
        digest = hashlib.sha256(content.encode()).hexdigest()
        with self.lock, self.db:
            self.db.execute("INSERT OR REPLACE INTO papers VALUES (?,?,?,?,?,?)",
                            (document_id, title, license, source_uri, content, digest))
        return digest

    def retrieve(self, query: str, *, limit: int = 5) -> list[dict]:
        if not query or limit < 1 or limit > 30:
            raise ValueError("Invalid retrieval query")
        # Conservative literal retrieval; search ranking is not entailment.
        pattern = "%" + query.replace("%", "\\%").replace("_", "\\_") + "%"
        with self.lock:
            rows = list(self.db.execute(
                "SELECT id,title,license,source_uri,content_hash FROM papers "
                "WHERE content LIKE ? ESCAPE '\\' LIMIT ?", (pattern, limit)))
        return [dict(zip(("id", "title", "license", "source_uri", "content_hash"), row))
                for row in rows]

    def quote(self, document_id: str, quote: str) -> PassageCheck:
        with self.lock:
            row = self.db.execute("SELECT content FROM papers WHERE id=?",
                                  (document_id,)).fetchone()
        if row is None or not quote or quote not in row[0]:
            return PassageCheck(False, document_id, None,
                                "quote not located in provided indexed corpus")
        return PassageCheck(True, document_id,
                            hashlib.sha256(quote.encode()).hexdigest(),
                            "Exact passage located; no semantic entailment or factual truth established")

    def close(self):
        with self.lock:
            self.db.close()
