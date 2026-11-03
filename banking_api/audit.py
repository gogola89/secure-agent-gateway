"""Append-only, hash-chained audit log (section 5).

One row is written for *every* request, allowed or denied. Each row's
`row_hash = sha256(prev_hash + canonical_json(row))`, so altering or
deleting any row breaks the chain for every row after it - `GET
/audit/verify` walks the chain and reports the first break. A Postgres
trigger (see the phase 4 migration) additionally raises on any UPDATE or
DELETE against this table, so the application can't even try.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from sqlalchemy import select

from banking_api.db import SessionLocal
from banking_api.models import AuditLog

GENESIS_HASH = "0" * 64

REDACTED = "***"
SENSITIVE_BODY_KEYS = {"password", "client_secret", "subject_token", "access_token", "otp"}


def _canonical(row: dict) -> str:
    return json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)


def _redact(value: object) -> object:
    if isinstance(value, dict):
        return {k: (REDACTED if k in SENSITIVE_BODY_KEYS else _redact(v)) for k, v in value.items()}
    return value


def write_audit_row(
    *,
    correlation_id: str,
    agent_id: str | None,
    customer_id: str | None,
    action: str,
    args_masked: dict,
    decision: str,
    reason: str | None,
    status_code: int,
    latency_ms: int,
) -> None:
    db = SessionLocal()
    try:
        # Lock the chain tip so concurrent requests append in series rather
        # than both reading the same prev_hash and forking the chain.
        prev_hash = db.execute(
            select(AuditLog.row_hash).order_by(AuditLog.id.desc()).limit(1).with_for_update()
        ).scalar()
        prev_hash = prev_hash or GENESIS_HASH

        row = {
            "correlation_id": correlation_id,
            "agent_id": agent_id,
            "customer_id": customer_id,
            "action": action,
            "args_masked": args_masked,
            "decision": decision,
            "reason": reason,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "prev_hash": prev_hash,
        }
        row_hash = hashlib.sha256((prev_hash + _canonical(row)).encode()).hexdigest()
        db.add(AuditLog(**row, row_hash=row_hash))
        db.commit()
    finally:
        db.close()


def verify_chain() -> dict:
    """Walks the chain in order; returns the id of the first row whose
    stored hash doesn't match a fresh recomputation, or None if intact."""
    db = SessionLocal()
    try:
        rows = db.query(AuditLog).order_by(AuditLog.id.asc()).all()
        prev_hash = GENESIS_HASH
        for row in rows:
            row_dict = {
                "correlation_id": row.correlation_id,
                "agent_id": row.agent_id,
                "customer_id": row.customer_id,
                "action": row.action,
                "args_masked": row.args_masked,
                "decision": row.decision,
                "reason": row.reason,
                "status_code": row.status_code,
                "latency_ms": row.latency_ms,
                "prev_hash": prev_hash,
            }
            expected = hashlib.sha256((prev_hash + _canonical(row_dict)).encode()).hexdigest()
            if expected != row.row_hash:
                return {"valid": False, "first_broken_row_id": row.id, "checked_rows": len(rows)}
            prev_hash = row.row_hash
        return {"valid": True, "first_broken_row_id": None, "checked_rows": len(rows)}
    finally:
        db.close()


async def _extract_args(request: Request) -> dict:
    args: dict = dict(request.path_params) | dict(request.query_params)
    if request.method in ("POST", "PUT", "PATCH"):
        body = await request.body()
        if body:
            with contextlib.suppress(ValueError):
                args["body"] = json.loads(body)
    return _redact(args)


async def audit_middleware(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    args_masked = await _extract_args(request)

    start = time.perf_counter()
    response = await call_next(request)
    latency_ms = int((time.perf_counter() - start) * 1000)

    status_code = response.status_code
    decision = "allowed" if status_code < 400 else "denied"
    reason = getattr(request.state, "deny_reason", None) if status_code >= 400 else None

    write_audit_row(
        correlation_id=correlation_id,
        agent_id=getattr(request.state, "agent_id", None),
        customer_id=getattr(request.state, "customer_id", None),
        action=f"{request.method} {request.url.path}",
        args_masked=args_masked,
        decision=decision,
        reason=reason,
        status_code=status_code,
        latency_ms=latency_ms,
    )

    response.headers["X-Correlation-ID"] = correlation_id
    return response
