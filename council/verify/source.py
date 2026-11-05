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

    def rfc_section_excerpt(self, section: str, *, max_chars: int = 900) -> dict | None:
        """Return a bounded, verbatim excerpt from an indexed official RFC.

        Heading lookup and excerpt retrieval establish provenance, NOT that
        any generated claim is correct. Do not return text from arbitrary
        uploaded documents mislabeled as RFC 9381.
        """
        import re
        if section not in {"3.1","3.3","3.4"} or not 300 <= max_chars <= 1500:
            raise ValueError("Invalid RFC section/excerpt request")
        with self.lock:
            row=self.db.execute(
                "SELECT source_uri,content,content_hash FROM papers WHERE id=?",
                ("rfc9381",)).fetchone()
        if not row or row[0] != "https://www.rfc-editor.org/rfc/rfc9381.txt":
            return None
        headings={"3.1":"Full Uniqueness","3.3":"Trusted Uniqueness",
                  "3.4":"Full Pseudorandomness"}
        content=row[1]
        pattern=r"(?m)^\s*"+re.escape(section)+r"\.\s+"+headings[section]+r"\s*$"
        matches=list(re.finditer(pattern,content))
        if not matches:
            return None
        # Last exact-line match avoids any table-of-contents occurrence.
        start=matches[-1].start()
        following=content[start:start+max_chars]
        return {"section":section,"title":headings[section],
                "document_id":"rfc9381","source_uri":row[0],
                "document_sha256":row[2],
                "excerpt":following,
                "truncated":start+max_chars<len(content)}

    def close(self):
        with self.lock:
            self.db.close()
