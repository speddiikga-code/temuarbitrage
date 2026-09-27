"""Append-only audit trail with a hash chain, so a removed or edited record is detectable."""

from __future__ import annotations

from .common import canonical_json, new_id, now_iso, sha256
from .db import Database, Tx

GENESIS = "0" * 64


class AuditTrail:
    def __init__(self, db: Database):
        self.db = db

    def record(self, tx: Tx, actor: str, action: str, entity_type: str, entity_id: str | None = None,
               before=None, after=None) -> str:
        """Append one record inside the caller's transaction and return its id."""
        tx.lock("audit")
        last = tx.fetchone("SELECT hash FROM audit_log ORDER BY seq DESC LIMIT 1")
        prev_hash = last["hash"] if last else GENESIS
        row = {
            "id": new_id("aud"),
            "at": now_iso(),
            "actor": actor,
            "action": action,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "before": canonical_json(before) if before is not None else None,
            "after": canonical_json(after) if after is not None else None,
            "prev_hash": prev_hash,
        }
        row["hash"] = self._hash(row)
        tx.insert("audit_log", row)
        return row["id"]

    @staticmethod
    def _hash(row: dict) -> str:
        material = {k: row[k] for k in ("id", "at", "actor", "action", "entity_type", "entity_id", "before", "after", "prev_hash")}
        return sha256(canonical_json(material))

    def verify(self) -> tuple[bool, int, int | None]:
        """Walk the chain. Returns (ok, records checked, first broken seq or None)."""
        with self.db.transaction() as tx:
            rows = tx.fetchall("SELECT * FROM audit_log ORDER BY seq")
        prev = GENESIS
        for row in rows:
            if row["prev_hash"] != prev or self._hash(row) != row["hash"]:
                return False, len(rows), row["seq"]
            prev = row["hash"]
        return True, len(rows), None

    def recent(self, limit: int = 50) -> list[dict]:
        with self.db.transaction() as tx:
            return tx.fetchall("SELECT * FROM audit_log ORDER BY seq DESC LIMIT ?", (limit,))
