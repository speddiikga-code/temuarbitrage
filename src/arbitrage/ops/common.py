"""Ids, clocks, canonical JSON and hashing shared by the operating core."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

SIMULATED = "simulated"
LIVE = "live"
MODES = (SIMULATED, LIVE)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:20]}"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def now_iso() -> str:
    return iso(utcnow())


def parse_iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def plus(dt: datetime, seconds: float) -> datetime:
    return dt + timedelta(seconds=seconds)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def fingerprint(value: Any) -> str:
    return sha256(canonical_json(value))


def check_mode(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, not {mode!r}")
    return mode


def loads(text: str | None, default=None):
    if text is None or text == "":
        return {} if default is None else default
    return json.loads(text)
