from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed import main as run_seed  # noqa: E402

from banking_api.db import SessionLocal, engine  # noqa: E402
from banking_api.main import app  # noqa: E402

TABLES_IN_TRUNCATE_ORDER = (
    "audit_log, outbox, notifications, transfers, transactions, "
    "beneficiaries, accounts, customers"
)


@pytest.fixture(scope="session", autouse=True)
def seeded_database():
    """Reset to a known-good seed once per test session, so the suite is
    deterministic regardless of what ran against this database before -
    the same database and migrations the app runs against in dev and CI
    (section 9: tests run against real Postgres and Redis, started by
    Compose), not a separate SQLite fixture DB."""
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE TABLE {TABLES_IN_TRUNCATE_ORDER} RESTART IDENTITY CASCADE"))
    run_seed()
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def db_session():
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
