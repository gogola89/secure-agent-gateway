from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.seed import main as run_seed  # noqa: E402

from banking_api.config import settings  # noqa: E402
from banking_api.db import SessionLocal, engine  # noqa: E402
from banking_api.main import app  # noqa: E402
from banking_api.redis_client import get_redis  # noqa: E402

AMINA_PHONE = "+254712345000"
BRIAN_PHONE = "+254723456000"
AGENT_CLIENT_ID = "assistant-v1"

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


@pytest.fixture(autouse=True)
def flush_rate_limits_and_otps():
    """Every test gets a clean Redis slate: without this, the rate limiter
    (keyed on agent_id:customer_id, section 5) would carry state across
    tests within the same real 60s window and start rejecting unrelated
    tests - a side effect of testing against real Redis rather than a
    mock, which is otherwise exactly what we want (section 9)."""
    get_redis().flushdb()
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


def _password_token(client: TestClient, phone: str) -> str:
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "password",
            "username": phone,
            "password": settings.demo_customer_password,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def _delegated_token(client: TestClient, full_token: str, client_id: str = AGENT_CLIENT_ID) -> str:
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": full_token,
            "client_id": client_id,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


@pytest.fixture
def amina_full_token(client: TestClient) -> str:
    return _password_token(client, AMINA_PHONE)


@pytest.fixture
def brian_full_token(client: TestClient) -> str:
    return _password_token(client, BRIAN_PHONE)


@pytest.fixture
def amina_token(client: TestClient, amina_full_token: str) -> str:
    """Delegated token: what the MCP server would hold for Amina."""
    return _delegated_token(client, amina_full_token)


@pytest.fixture
def brian_token(client: TestClient, brian_full_token: str) -> str:
    return _delegated_token(client, brian_full_token)


@pytest.fixture
def agent_token(client: TestClient) -> str:
    agent = settings.agent_credentials()[AGENT_CLIENT_ID]
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": agent.client_id,
            "client_secret": agent.client_secret,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["access_token"]


def auth_headers(customer_token: str, agent_token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {customer_token}",
        "X-Agent-Token": agent_token,
    }
