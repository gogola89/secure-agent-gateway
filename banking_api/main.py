from __future__ import annotations

import redis
from fastapi import FastAPI
from sqlalchemy import text

from banking_api.config import settings
from banking_api.db import engine

app = FastAPI(title="Secure Agent Gateway - Banking API", version="0.1.0")


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
