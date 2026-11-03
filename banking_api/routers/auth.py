"""Mock IdP endpoint. `password` and `client_credentials` stand in for a
real Authorization Code + PKCE flow and a real client-credentials flow -
good enough to demonstrate the gateway pattern, never meant to be a real
authentication mechanism (section 5).

The token-exchange grant (RFC 8693) is the one grant that matters for the
gateway's design: it narrows a customer's own token to the subset an agent
is allowed to act with, by construction excluding `transfers:confirm`.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from banking_api.auth import (
    CUSTOMER_FULL_SCOPES,
    SCOPES_NEVER_DELEGATED,
    TOKEN_EXCHANGE_GRANT,
    create_agent_token,
    create_customer_token,
    decode_token,
)
from banking_api.config import settings
from banking_api.db import get_db
from banking_api.errors import AppError, error_responses
from banking_api.models import Customer
from banking_api.schemas import TokenRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _token_response(access_token: str, scopes: list[str]) -> TokenResponse:
    return TokenResponse(
        access_token=access_token,
        expires_in=settings.jwt_access_token_ttl_seconds,
        scope=" ".join(scopes),
    )


def _password_grant(body: TokenRequest, db: Session) -> TokenResponse:
    if not body.username or not body.password:
        raise AppError(400, "invalid_request", "username and password are required.")
    if body.password != settings.demo_customer_password:
        raise AppError(401, "invalid_credentials", "Incorrect username or password.")

    customer = db.query(Customer).filter_by(phone=body.username).one_or_none()
    if customer is None:
        raise AppError(401, "invalid_credentials", "Incorrect username or password.")

    token = create_customer_token(str(customer.id), CUSTOMER_FULL_SCOPES)
    return _token_response(token, CUSTOMER_FULL_SCOPES)


def _client_credentials_grant(body: TokenRequest) -> TokenResponse:
    if not body.client_id or not body.client_secret:
        raise AppError(400, "invalid_request", "client_id and client_secret are required.")

    agents = settings.agent_credentials()
    agent = agents.get(body.client_id)
    if agent is None or agent.client_secret != body.client_secret:
        raise AppError(401, "invalid_client", "Unknown client_id or wrong client_secret.")

    token = create_agent_token(agent.client_id, agent.scopes)
    return _token_response(token, agent.scopes)


def _token_exchange_grant(body: TokenRequest) -> TokenResponse:
    if not body.subject_token or not body.client_id:
        raise AppError(400, "invalid_request", "subject_token and client_id are required.")

    agents = settings.agent_credentials()
    if body.client_id not in agents:
        raise AppError(400, "invalid_target", f"Unknown delegate client_id '{body.client_id}'.")

    claims = decode_token(body.subject_token)
    subject_scopes = set(claims.get("scope", "").split())
    delegated_scopes = sorted(subject_scopes - SCOPES_NEVER_DELEGATED)

    token = create_customer_token(claims["sub"], delegated_scopes, azp=body.client_id)
    return _token_response(token, delegated_scopes)


@router.post(
    "/token",
    response_model=TokenResponse,
    responses=error_responses(400, 401, 422),
)
def issue_token(body: TokenRequest, db: Session = Depends(get_db)) -> TokenResponse:
    if body.grant_type == "password":
        return _password_grant(body, db)
    if body.grant_type == "client_credentials":
        return _client_credentials_grant(body)
    if body.grant_type == TOKEN_EXCHANGE_GRANT:
        return _token_exchange_grant(body)
    raise AppError(400, "unsupported_grant_type", f"Unsupported grant_type '{body.grant_type}'.")
