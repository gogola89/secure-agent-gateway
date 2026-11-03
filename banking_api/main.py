from __future__ import annotations

import uuid

import redis
from fastapi import FastAPI, Request
from sqlalchemy import text

from banking_api.config import settings
from banking_api.db import engine
from banking_api.errors import register_exception_handlers
from banking_api.routers import accounts, auth

app = FastAPI(title="Secure Agent Gateway - Banking API", version="0.1.0")
register_exception_handlers(app)
app.include_router(auth.router)
app.include_router(accounts.router)


@app.middleware("http")
async def correlation_id_middleware(request: Request, call_next):
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    response = await call_next(request)
    response.headers["X-Correlation-ID"] = correlation_id
    return response


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict[str, str]:
    """Readiness: can this instance actually serve traffic right now?"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    redis_client = redis.Redis.from_url(settings.redis_url)
    redis_client.ping()

    return {"status": "ready"}
