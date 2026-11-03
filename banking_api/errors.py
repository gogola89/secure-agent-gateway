"""Uniform error envelope: {"error": {"code", "message", "correlation_id"}}
for every error response, everywhere. Never leak stack traces (section 5)."""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class AppError(Exception):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        super().__init__(message)


def _correlation_id(request: Request) -> str:
    return getattr(request.state, "correlation_id", "unknown")


def _envelope(status_code: int, code: str, message: str, correlation_id: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "correlation_id": correlation_id}},
        headers={"X-Correlation-ID": correlation_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.status_code, exc.code, exc.message, _correlation_id(request))

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return _envelope(
            422, "validation_error", "Request failed schema validation.", _correlation_id(request)
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 429: "rate_limited"}.get(
            exc.status_code, "http_error"
        )
        detail = exc.detail if isinstance(exc.detail, str) else code
        return _envelope(exc.status_code, code, detail, _correlation_id(request))

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        return _envelope(
            500, "internal_error", "An internal error occurred.", _correlation_id(request)
        )
