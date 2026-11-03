from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text

from banking_api.audit import audit_middleware
from banking_api.db import engine
from banking_api.errors import error_responses, register_exception_handlers
from banking_api.redis_client import get_redis
from banking_api.routers import accounts, auth, transfers
from banking_api.routers import audit as audit_router

DOCS_DIR = Path(__file__).resolve().parent / "static" / "docs"

# /docs is the human documentation site (installation, architecture,
# security design, usage) mounted below - so FastAPI's own interactive API
# reference moves to /api-docs instead of its default /docs.
app = FastAPI(
    title="Secure Agent Gateway - Banking API",
    version="0.1.0",
    docs_url="/api-docs",
)
register_exception_handlers(app)
app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transfers.router)
app.include_router(audit_router.router)

app.mount("/docs", StaticFiles(directory=DOCS_DIR, html=True), name="docs")

app.middleware("http")(audit_middleware)


@app.get("/healthz")
def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependency checks."""
    return {"status": "ok"}


@app.get("/readyz", responses=error_responses(500))
def readyz() -> dict[str, str]:
    """Readiness: can this instance actually serve traffic right now?"""
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))

    get_redis().ping()

    return {"status": "ready"}
