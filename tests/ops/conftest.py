"""Every operating-core test runs on SQLite. Set OPSCORE_TEST_DATABASE_URL=postgresql://... to run each on PostgreSQL too."""

import os
import uuid
from pathlib import Path

import pytest

from arbitrage.ops.db import Database
from arbitrage.ops.mandate import load_mandate, parse_mandate, pending_mandate

ROOT = Path(__file__).resolve().parents[2]
PG_URL = os.environ.get("OPSCORE_TEST_DATABASE_URL")

BACKENDS = ["sqlite"] + (["postgresql"] if PG_URL else [])


@pytest.fixture(params=BACKENDS)
def db(request, tmp_path):
    if request.param == "sqlite":
        database = Database(f"sqlite:///{tmp_path / 'ops.db'}")
    else:
        database = Database(PG_URL)
        database.reset()
    database.migrate()
    yield database
    if request.param == "postgresql":
        database.reset()


@pytest.fixture
def simulated_mandate():
    return load_mandate(ROOT / "mandate.simulated.toml")


@pytest.fixture
def pending():
    return pending_mandate()


def mandate_with(**overrides):
    """The simulated mandate with some values replaced (dotted names like limits.max_transaction_krw)."""
    import tomllib

    data = tomllib.loads((ROOT / "mandate.simulated.toml").read_text("utf-8"))
    for name, value in overrides.items():
        section, key = name.split(".")
        data.setdefault(section, {})[key] = value
    return parse_mandate(data, f"<override {uuid.uuid4().hex[:6]}>")
