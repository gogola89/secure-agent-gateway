"""Section 9: Idempotency, Limits, OTP, Confirm, and the prompt-injection
end-to-end check (reading a poisoned narration never creates a transfer)."""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from banking_api.config import settings
from banking_api.main import app
from banking_api.models import Transfer

from .conftest import auth_headers

OTP_RE = re.compile(r"your OTP is (\d{6})")


def _idem_key() -> str:
    return uuid.uuid4().hex


def _latest_otp() -> str:
    lines = Path(settings.sms_outbox_path).read_text().splitlines()
    match = OTP_RE.search(lines[-1])
    assert match, f"no OTP found in last SMS line: {lines[-1]!r}"
    return match.group(1)


def _initiate(
    client, amina_token, agent_token, *, amount_kes, narration, beneficiary="BEN-1", key=None
):
    return client.post(
        "/transfers",
        headers={**auth_headers(amina_token, agent_token), "Idempotency-Key": key or _idem_key()},
        json={
            "from_account_alias": "ACC-1",
            "beneficiary_alias": beneficiary,
            "amount_kes": amount_kes,
            "narration": narration,
        },
    )


# --- Idempotency ---


def test_initiate_creates_pending_transfer_and_sends_otp(client, amina_token, agent_token):
    response = _initiate(client, amina_token, agent_token, amount_kes="5000.00", narration="Lunch")
    assert response.status_code == 201
    assert response.json()["status"] == "pending_confirmation"
    assert len(_latest_otp()) == 6


def test_idempotent_replay_returns_same_transfer(client, amina_token, agent_token):
    key = _idem_key()
    first = _initiate(
        client, amina_token, agent_token, amount_kes="1000.00", narration="Replay", key=key
    )
    second = _initiate(
        client, amina_token, agent_token, amount_kes="1000.00", narration="Replay", key=key
    )
    assert first.status_code == 201
    assert second.status_code == 200
    assert second.headers["Idempotent-Replay"] == "true"
    assert second.json()["transfer_id"] == first.json()["transfer_id"]


def test_same_key_different_body_is_conflict(client, amina_token, agent_token):
    key = _idem_key()
    _initiate(client, amina_token, agent_token, amount_kes="1000.00", narration="A", key=key)
    conflict = _initiate(
        client, amina_token, agent_token, amount_kes="2000.00", narration="B", key=key
    )
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "idempotency_key_reuse"


def test_concurrent_identical_requests_create_exactly_one_transfer(amina_token, agent_token):
    import concurrent.futures

    key = _idem_key()

    def fire(_: int):
        return _initiate(
            TestClient(app),
            amina_token,
            agent_token,
            amount_kes="500.00",
            narration="Race",
            key=key,
        )

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        results = list(pool.map(fire, range(10)))

    assert all(r.status_code in (200, 201) for r in results)
    assert len({r.json()["transfer_id"] for r in results}) == 1


# --- Limits ---


def test_amount_just_above_per_transfer_limit_is_rejected(client, amina_token, agent_token):
    response = _initiate(
        client, amina_token, agent_token, amount_kes="100000.01", narration="Too big"
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "amount_exceeds_limit"


def test_daily_total_above_limit_is_rejected(client, amina_token, agent_token):
    first = _initiate(client, amina_token, agent_token, amount_kes="90000.00", narration="Big 1")
    assert first.status_code == 201
    second = _initiate(client, amina_token, agent_token, amount_kes="90000.00", narration="Big 2")
    assert second.status_code == 422
    assert second.json()["error"]["code"] == "daily_limit_exceeded"


def test_insufficient_balance_is_rejected(client, brian_token, agent_token):
    response = client.post(
        "/transfers",
        headers={**auth_headers(brian_token, agent_token), "Idempotency-Key": _idem_key()},
        json={
            "from_account_alias": "ACC-1",
            "beneficiary_alias": "BEN-1",
            "amount_kes": "92301.00",
            "narration": "More than Brian has",
        },
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "insufficient_balance"


# --- OTP and confirm ---


def test_wrong_otp_three_times_rejects_the_transfer(
    client, amina_token, agent_token, amina_full_token
):
    initiate = _initiate(
        client, amina_token, agent_token, amount_kes="1000.00", narration="OTP test"
    )
    transfer_id = initiate.json()["transfer_id"]
    headers = {"Authorization": f"Bearer {amina_full_token}"}

    for _ in range(2):
        resp = client.post(
            f"/transfers/{transfer_id}/confirm", json={"otp": "000000"}, headers=headers
        )
        assert resp.status_code == 401
        assert resp.json()["error"]["code"] == "otp_incorrect"

    final = client.post(
        f"/transfers/{transfer_id}/confirm", json={"otp": "000000"}, headers=headers
    )
    assert final.status_code == 409
    assert final.json()["error"]["code"] == "otp_max_attempts_exceeded"

    status = client.get(f"/transfers/{transfer_id}", headers=auth_headers(amina_token, agent_token))
    assert status.json()["status"] == "rejected"


def test_expired_otp_marks_transfer_expired(
    client, amina_token, agent_token, amina_full_token, db_session
):
    initiate = _initiate(
        client, amina_token, agent_token, amount_kes="1000.00", narration="Expiry test"
    )
    transfer_id = initiate.json()["transfer_id"]
    otp = _latest_otp()

    transfer = db_session.get(Transfer, transfer_id)
    transfer.created_at = datetime.now(UTC) - timedelta(seconds=settings.otp_ttl_seconds + 30)
    db_session.commit()

    response = client.post(
        f"/transfers/{transfer_id}/confirm",
        json={"otp": otp},
        headers={"Authorization": f"Bearer {amina_full_token}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "transfer_expired"


def test_agent_token_on_confirm_is_rejected_even_with_a_valid_otp(
    client, amina_token, agent_token, amina_full_token
):
    initiate = _initiate(
        client, amina_token, agent_token, amount_kes="1500.00", narration="No agents"
    )
    transfer_id = initiate.json()["transfer_id"]
    otp = _latest_otp()

    response = client.post(
        f"/transfers/{transfer_id}/confirm",
        json={"otp": otp},
        headers={"Authorization": f"Bearer {amina_full_token}", "X-Agent-Token": agent_token},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "agents_cannot_confirm"


def test_confirming_an_already_completed_transfer_never_debits_twice(
    client, amina_token, agent_token, amina_full_token
):
    initiate = _initiate(
        client, amina_token, agent_token, amount_kes="2000.00", narration="Once only"
    )
    transfer_id = initiate.json()["transfer_id"]
    otp = _latest_otp()
    headers = {"Authorization": f"Bearer {amina_full_token}"}

    first = client.post(f"/transfers/{transfer_id}/confirm", json={"otp": otp}, headers=headers)
    assert first.status_code == 200
    assert first.json()["status"] == "completed"

    balance_after_first = next(
        a["balance_kes"]
        for a in client.get("/accounts", headers=auth_headers(amina_token, agent_token)).json()
        if a["alias"] == "ACC-1"
    )

    second = client.post(f"/transfers/{transfer_id}/confirm", json={"otp": otp}, headers=headers)
    assert second.status_code == 200
    assert second.json()["status"] == "completed"

    balance_after_second = next(
        a["balance_kes"]
        for a in client.get("/accounts", headers=auth_headers(amina_token, agent_token)).json()
        if a["alias"] == "ACC-1"
    )
    assert balance_after_first == balance_after_second


# --- Prompt injection ---


def test_reading_poisoned_narration_never_creates_a_transfer(
    client, amina_token, agent_token, db_session
):
    before = db_session.query(Transfer).count()
    response = client.get(
        "/accounts/ACC-2/transactions?limit=20", headers=auth_headers(amina_token, agent_token)
    )
    assert "IGNORE ALL PREVIOUS INSTRUCTIONS" in response.text
    after = db_session.query(Transfer).count()
    assert after == before
