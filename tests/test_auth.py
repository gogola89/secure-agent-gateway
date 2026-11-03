"""Section 9: Tokens - expired, wrong aud, wrong iss, alg=none and HS256
tokens are rejected with 401. Scopes - effective scopes are the
intersection of customer and agent scopes."""

from __future__ import annotations

import time

import jwt

from banking_api import auth
from banking_api.config import settings

from .conftest import auth_headers


def _tampered_token(**overrides) -> str:
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": "some-customer-id",
        "scope": "accounts:read",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
    }
    payload.update(overrides)
    return jwt.encode(payload, auth._private_key(), algorithm="RS256")


def test_expired_token_is_rejected(client, agent_token):
    bad = _tampered_token(exp=int(time.time()) - 10)
    response = client.get("/accounts", headers=auth_headers(bad, agent_token))
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_token"


def test_wrong_audience_is_rejected(client, agent_token):
    bad = _tampered_token(aud="some-other-api")
    response = client.get("/accounts", headers=auth_headers(bad, agent_token))
    assert response.status_code == 401


def test_wrong_issuer_is_rejected(client, agent_token):
    bad = _tampered_token(iss="some-other-idp")
    response = client.get("/accounts", headers=auth_headers(bad, agent_token))
    assert response.status_code == 401


def test_alg_none_is_rejected(client, agent_token):
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": "some-customer-id",
        "scope": "accounts:read",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
    }
    bad = jwt.encode(payload, key=None, algorithm="none")
    response = client.get("/accounts", headers=auth_headers(bad, agent_token))
    assert response.status_code == 401


def test_hs256_token_is_rejected(client, agent_token):
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": "some-customer-id",
        "scope": "accounts:read",
        "iat": now,
        "nbf": now,
        "exp": now + 900,
    }
    # Even if an attacker guesses the exact HS256 "secret" below, the server
    # only ever accepts RS256, so symmetric-key confusion attacks fail here.
    bad = jwt.encode(payload, key="whatever-secret-an-attacker-might-try", algorithm="HS256")
    response = client.get("/accounts", headers=auth_headers(bad, agent_token))
    assert response.status_code == 401


def test_missing_tokens_are_rejected(client):
    assert client.get("/accounts").status_code == 401


def test_missing_agent_token_header_is_rejected(client, amina_full_token):
    response = client.get("/accounts", headers={"Authorization": f"Bearer {amina_full_token}"})
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "missing_agent_token"


def test_wrong_password_is_rejected(client):
    response = client.post(
        "/auth/token",
        json={"grant_type": "password", "username": "+254712345000", "password": "nope"},
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_unknown_customer_phone_is_rejected(client):
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "password",
            "username": "+254700000000",
            "password": settings.demo_customer_password,
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_credentials"


def test_unknown_agent_client_credentials_are_rejected(client):
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "client_credentials",
            "client_id": "assistant-v1",
            "client_secret": "wrong-secret",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "invalid_client"


def test_token_exchange_with_unknown_delegate_is_rejected(client, amina_full_token):
    response = client.post(
        "/auth/token",
        json={
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "subject_token": amina_full_token,
            "client_id": "no-such-agent",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_target"


def test_unsupported_grant_type_is_rejected(client):
    response = client.post("/auth/token", json={"grant_type": "implicit"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "unsupported_grant_type"


def test_effective_scopes_are_the_intersection(client, amina_full_token):
    narrow_agent_token = auth.create_agent_token("assistant-v1", ["transactions:read"])
    response = client.get("/accounts", headers=auth_headers(amina_full_token, narrow_agent_token))
    assert response.status_code == 403
    assert response.json()["error"]["message"] == "scope_missing:accounts:read"


def test_confirm_scope_is_never_granted_to_the_agent(client, agent_token):
    claims = auth.decode_token(agent_token)
    assert "transfers:confirm" not in claims["scope"].split()


def test_token_exchange_narrows_scopes(client, amina_full_token, amina_token):
    full_claims = auth.decode_token(amina_full_token)
    delegated_claims = auth.decode_token(amina_token)
    assert "transfers:confirm" in full_claims["scope"].split()
    assert "transfers:confirm" not in delegated_claims["scope"].split()
    assert delegated_claims["azp"] == "assistant-v1"
