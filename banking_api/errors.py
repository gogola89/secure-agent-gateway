"""Uniform error envelope: {"error": {"code", "message", "correlation_id"}}
for every error response, everywhere. Never leak stack traces (section 5)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    """`audit_reason` is for the audit log only (section 5): it may be more
    specific than what the API is allowed to tell the caller - for example
    distinguishing "not_owner" from "not_found" so the public 404 body
    stays identical either way, while the audit trail still records which
    one actually happened."""

    def __init__(
        self,
        status_code: int,
        code: str,
        message: str,
        audit_reason: str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.audit_reason = audit_reason or code
        self.headers = headers or {}
        super().__init__(message)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _envelope(
    status_code: int,
    code: str,
    message: str,
    correlation_id: str,
    extra_headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers={"X-Correlation-ID": correlation_id, **(extra_headers or {})},
    )


def register_exception_handlers(app: FastAPI) -> None:
    # Each handler stashes a reason on request.state: the audit middleware
    # wraps call_next, so by the time it sees the response these handlers
    # have already turned the exception into a JSONResponse - this is the
    # only channel left for the audit row to learn *why* something was
    # denied, since AppError itself never reaches the middleware's `except`.
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        request.state.deny_reason = exc.audit_reason
        return _envelope(
            exc.status_code, exc.code, exc.message, _correlation_id(request), exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request.state.deny_reason = "validation_error"
        return _envelope(
            422, "validation_error", "Request failed schema validation.", _correlation_id(request)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(
            exc.status_code, "http_error"
        )
        detail = exc.detail if isinstance(exc.detail, str) else code
        request.state.deny_reason = code
        return _envelope(exc.status_code, code, detail, _correlation_id(request))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request.state.deny_reason = "internal_error"
        return _envelope(
            500, "internal_error", "An internal error occurred.", _correlation_id(request)
        )
