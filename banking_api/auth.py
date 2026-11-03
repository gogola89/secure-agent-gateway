"""JWT issue/verify, scopes and the "current principal" dependencies.

Nothing here ever reads a customer_id from a request body or query string:
identity comes only from the signed tokens in this module, which is the
whole point of the gateway (section 1, "identity from the token, never
from the model").
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from functools import lru_cache

import jwt
from fastapi import Depends, Header, Request

from banking_api.config import settings
from banking_api.errors import AppError

ALLOWED_ALGORITHMS = ["RS256"]


@lru_cache
def _private_key() -> str:
    with open(settings.jwt_private_key_path) as f:
        return f.read()


@lru_cache
def _public_key() -> str:
    with open(settings.jwt_public_key_path) as f:
        return f.read()


def _encode(sub: str, scopes: list[str], extra_claims: dict) -> str:
    now = int(time.time())
    payload = {
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "sub": sub,
        "scope": " ".join(scopes),
        "iat": now,
        "nbf": now,
        "exp": now + settings.jwt_access_token_ttl_seconds,
        "jti": str(uuid.uuid4()),
        **extra_claims,
    }
    return jwt.encode(payload, _private_key(), algorithm="RS256")


def create_customer_token(customer_id: str, scopes: list[str], azp: str | None = None) -> str:
    extra = {"azp": azp} if azp else {}
    return _encode(customer_id, scopes, extra)


def create_agent_token(agent_id: str, scopes: list[str]) -> str:
    return _encode(agent_id, scopes, {})


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            _public_key(),
            algorithms=ALLOWED_ALGORITHMS,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["exp", "iat", "nbf", "sub", "scope"]},
        )
    except jwt.PyJWTError as exc:
        raise AppError(401, "invalid_token", f"Token rejected: {exc}") from exc


@dataclass(frozen=True)
class Principal:
    sub: str
    scopes: set[str]
    azp: str | None = None


def _principal_from_bearer(value: str | None) -> Principal:
    if not value or not value.startswith("Bearer "):
        raise AppError(401, "missing_token", "Authorization: Bearer <token> is required.")
    claims = decode_token(value.removeprefix("Bearer ").strip())
    return Principal(
        sub=claims["sub"],
        scopes=set(claims.get("scope", "").split()),
        azp=claims.get("azp"),
    )


def get_customer_principal(authorization: str | None = Header(default=None)) -> Principal:
    return _principal_from_bearer(authorization)


def get_agent_principal(
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> Principal:
    if not x_agent_token:
        raise AppError(401, "missing_agent_token", "X-Agent-Token header is required.")
    claims = decode_token(x_agent_token)
    return Principal(sub=claims["sub"], scopes=set(claims.get("scope", "").split()))


@dataclass(frozen=True)
class EffectivePrincipal:
    customer_id: str
    agent_id: str
    effective_scopes: set[str]


def get_effective_principal(
    request: Request,
    authorization: str | None = Header(default=None),
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
) -> EffectivePrincipal:
    customer = get_customer_principal(authorization)
    agent = get_agent_principal(x_agent_token)
    effective = customer.scopes & agent.scopes
    principal = EffectivePrincipal(
        customer_id=customer.sub, agent_id=agent.sub, effective_scopes=effective
    )
    request.state.customer_id = principal.customer_id
    request.state.agent_id = principal.agent_id
    return principal


def require_scopes(*required: str):
    def checked(
        principal: EffectivePrincipal = Depends(get_effective_principal),
    ) -> EffectivePrincipal:
        missing = set(required) - principal.effective_scopes
        if missing:
            reason = f"scope_missing:{','.join(sorted(missing))}"
            raise AppError(403, "forbidden", reason)
        return principal

    return checked
