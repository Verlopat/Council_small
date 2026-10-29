"""Queryable persistent claim/evidence ledger snapshots for one Council run.

EventStore is the append-only audit log; this is a materialized SQLite
projection, never a second authority that can override verified evidence.
"""
from __future__ import annotations
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from council.models import Claim, ClaimLedger, Evidence, ClaimStatus, EvidenceKind
from council.dependencies import Dependency

class SQLiteLedger:
    def __init__(self, location: Path | sqlite3.Connection):
        self.owns_connection=not isinstance(location,sqlite3.Connection)
        self.db=sqlite3.connect(location) if self.owns_connection else location
        self.db.execute("""CREATE TABLE IF NOT EXISTS council_claim_snapshots(
            run_id TEXT NOT NULL, claim_id TEXT NOT NULL,
            version INTEGER NOT NULL, status TEXT NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(run_id,claim_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS council_evidence_snapshots(
            run_id TEXT NOT NULL, evidence_id TEXT NOT NULL,
            claim_id TEXT NOT NULL, claim_version INTEGER NOT NULL,
            source_id TEXT, payload TEXT NOT NULL,
            PRIMARY KEY(run_id,evidence_id))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS council_argument_snapshots(
            run_id TEXT NOT NULL, edge_index INTEGER NOT NULL,
            premise_id TEXT NOT NULL, dependent_id TEXT NOT NULL,
            valid_support INTEGER NOT NULL,
            payload TEXT NOT NULL, PRIMARY KEY(run_id,edge_index))""")
        self.db.commit()

    def save(self,run_id:str,ledger:ClaimLedger)->None:
        if not run_id:
            raise ValueError("Run ID required")
        # Snapshot atomically. The log records immutable earlier versions.
        with self.db:
            for table in ("council_claim_snapshots","council_evidence_snapshots",
                          "council_argument_snapshots"):
                self.db.execute("DELETE FROM "+table+" WHERE run_id=?",(run_id,))
            for claim in ledger.claims.values():
                self.db.execute(
                    "INSERT INTO council_claim_snapshots VALUES(?,?,?,?,?)",
                    (run_id,claim.id,claim.version,claim.status.value,
                     json.dumps(asdict(claim),ensure_ascii=False)))
            for evidence in ledger.evidence.values():
                self.db.execute(
                    "INSERT INTO council_evidence_snapshots VALUES(?,?,?,?,?,?)",
                    (run_id,evidence.id,evidence.claim_id,evidence.claim_version,
                     evidence.source_id,json.dumps(asdict(evidence),ensure_ascii=False)))
            for index,edge in enumerate(ledger.argument_dependencies.edges):
                self.db.execute(
                    "INSERT INTO council_argument_snapshots VALUES(?,?,?,?,?,?)",
                    (run_id,index,edge.premise_id,edge.dependent_id,
                     int(edge.valid_support),
                     json.dumps(asdict(edge),ensure_ascii=False)))

    def load(self,run_id:str)->ClaimLedger:
        ledger=ClaimLedger()
        claims=self.db.execute("SELECT payload FROM council_claim_snapshots "
                               "WHERE run_id=? ORDER BY claim_id",(run_id,))
        for (payload,) in claims:
            value=json.loads(payload)
            value["status"]=ClaimStatus(value["status"])
            ledger.add_claim(Claim(**value))
        evidences=self.db.execute("SELECT payload FROM council_evidence_snapshots "
                                  "WHERE run_id=? ORDER BY evidence_id",(run_id,))
        for (payload,) in evidences:
            value=json.loads(payload)
            value["kind"]=EvidenceKind(value["kind"])
            for field in ("assumptions","provenance"):
                value[field]=tuple(value.get(field) or ())
            item=Evidence(**value)
            if item.claim_id not in ledger.claims:
                raise ValueError("Orphaned stored evidence")
            ledger.evidence[item.id]=item
        edges=self.db.execute("SELECT payload FROM council_argument_snapshots "
                              "WHERE run_id=? ORDER BY edge_index",(run_id,))
        for (payload,) in edges:
            value=json.loads(payload)
            value["evidence_ids"]=tuple(value.get("evidence_ids") or ())
            ledger.argument_dependencies.edges.append(Dependency(**value))
        return ledger

    def close(self):
        if self.owns_connection:
            self.db.close()
