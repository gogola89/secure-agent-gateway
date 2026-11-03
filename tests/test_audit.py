"""Section 9: Audit - every request, allowed or denied, writes exactly one
row; tampering with a row makes /audit/verify fail at that row; UPDATE on
audit_log raises."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from banking_api.config import settings
from banking_api.models import AuditLog

from .conftest import auth_headers

ADMIN_HEADERS = {"Authorization": f"Bearer {settings.admin_token}"}


def test_every_allowed_and_denied_request_writes_exactly_one_row(
    client, amina_token, agent_token, db_session
):
    def row_count() -> int:
        return db_session.query(AuditLog).count()

    before_allowed = row_count()
    allowed = client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    assert allowed.status_code == 200
    assert row_count() == before_allowed + 1

    before_denied = row_count()
    denied = client.get("/accounts")
    assert denied.status_code == 401
    assert row_count() == before_denied + 1

    last_row = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert last_row.decision == "denied"
    assert last_row.status_code == 401


def test_audit_rows_never_contain_secrets(client, amina_full_token, db_session):
    client.post(
        "/auth/token",
        json={"grant_type": "password", "username": "+254712345000", "password": "wrong-password"},
    )
    last_row = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert "wrong-password" not in str(last_row.args_masked)


def test_audit_verify_passes_on_an_untampered_chain(client, amina_token, agent_token):
    client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    response = client.get("/audit/verify", headers=ADMIN_HEADERS)
    assert response.status_code == 200
    assert response.json()["valid"] is True


def test_audit_verify_requires_admin_token(client):
    response = client.get("/audit/verify")
    assert response.status_code == 401


def test_audit_verify_detects_a_tampered_row(client, amina_token, agent_token, db_session):
    client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    row = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    original_reason = row.reason

    # Simulate an attacker with raw DB access deliberately bypassing the
    # append-only trigger - the only way any UPDATE reaches this table.
    # Restored at the end: this suite runs against the same dev database
    # as the live demo, and a tampered row left behind would permanently
    # fail /audit/verify for anyone running the app afterwards.
    try:
        db_session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_no_update_delete"))
        db_session.execute(
            text("UPDATE audit_log SET reason = :reason WHERE id = :id"),
            {"reason": "tampered", "id": row.id},
        )
        db_session.commit()

        response = client.get("/audit/verify", headers=ADMIN_HEADERS)
        body = response.json()
        assert body["valid"] is False
        assert body["first_broken_row_id"] == row.id
    finally:
        db_session.execute(
            text("UPDATE audit_log SET reason = :reason WHERE id = :id"),
            {"reason": original_reason, "id": row.id},
        )
        db_session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_no_update_delete"))
        db_session.commit()


def test_update_on_audit_log_raises(db_session):
    row = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row is not None
    with pytest.raises(DBAPIError):
        db_session.execute(text("UPDATE audit_log SET reason = 'x' WHERE id = :id"), {"id": row.id})
        db_session.commit()
    db_session.rollback()


def test_delete_on_audit_log_raises(db_session):
    row = db_session.query(AuditLog).order_by(AuditLog.id.desc()).first()
    assert row is not None
    with pytest.raises(DBAPIError):
        db_session.execute(text("DELETE FROM audit_log WHERE id = :id"), {"id": row.id})
        db_session.commit()
    db_session.rollback()
