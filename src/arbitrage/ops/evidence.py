"""Evidence store: invoices, receipts, quotes, screenshots and reports, content-addressed and tied to a record.

Files live under a root directory (object storage later: the `uri` column is the only thing that changes); the
table holds the hash, size and what the file is evidence for.  Nothing is ever overwritten.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from .common import check_mode, new_id, now_iso
from .db import Database, Tx
from .errors import OpsError


class EvidenceStore:
    def __init__(self, db: Database, root: str | Path):
        self.db = db
        self.root = Path(root)

    def put(self, tx: Tx, kind: str, data: bytes, filename: str, related_type: str, related_id: str, mode: str) -> dict:
        check_mode(mode)
        if not data:
            raise OpsError("evidence is empty")
        digest = hashlib.sha256(data).hexdigest()
        evidence_id = new_id("ev")
        safe = "".join(c if c.isalnum() or c in "._-" else "_" for c in filename)[:80] or "file"
        path = self.root / mode / f"{evidence_id}_{safe}"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        row = {"id": evidence_id, "kind": kind, "uri": path.resolve().as_uri(), "sha256": digest, "size": len(data),
               "related_type": related_type, "related_id": related_id, "created_at": now_iso(), "mode": mode}
        tx.insert("evidence", row)
        return row

    def get(self, tx: Tx, evidence_id: str) -> dict:
        row = tx.fetchone("SELECT * FROM evidence WHERE id = ?", (evidence_id,))
        if not row:
            raise OpsError(f"unknown evidence {evidence_id}")
        return row

    def read(self, row: dict) -> bytes:
        path = Path(row["uri"].removeprefix("file://"))
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise OpsError(f"evidence {row['id']} does not match its recorded hash")
        return data

    def for_record(self, tx: Tx, related_type: str, related_id: str) -> list[dict]:
        return tx.fetchall("SELECT * FROM evidence WHERE related_type = ? AND related_id = ? ORDER BY created_at", (related_type, related_id))
