"""Resilient HTTP client from the MCP server to the banking API
(section 6). Every call sends both tokens and a fresh correlation ID.

- Timeouts: connect 2s, read 5s.
- GET requests retry up to 3 times with exponential backoff and jitter.
- POST /transfers retries only with the *same* Idempotency-Key (true by
  construction here: the key is computed once by the caller and passed in,
  never regenerated between attempts).
- A circuit breaker opens after 5 consecutive failures for 30s and raises a
  clear "banking service temporarily unavailable" error instead of
  continuing to hammer a dependency that's already down.
- 4xx responses (bad alias, missing scope, business-rule rejection, ...)
  are translated into `BankingAPIError` but never retried and never count
  as a circuit-breaker failure - they're an answer, not an outage.
"""

from __future__ import annotations

import time
import uuid

import httpx
import pybreaker
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential_jitter

from mcp_server.config import mcp_settings


class BankingAPIError(Exception):
    def __init__(
        self, message: str, status_code: int | None = None, code: str | None = None
    ) -> None:
        self.status_code = status_code
        self.code = code
        super().__init__(message)


def _is_retryable(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError | httpx.TimeoutException):
        return True
    return isinstance(exc, BankingAPIError) and bool(exc.status_code) and exc.status_code >= 500


class BankingAPIClient:
    def __init__(self) -> None:
        self._http = httpx.Client(
            base_url=mcp_settings.banking_api_url,
            timeout=httpx.Timeout(connect=2.0, read=5.0, write=5.0, pool=5.0),
        )
        self.session_id = str(uuid.uuid4())
        self.circuit_breaker = pybreaker.CircuitBreaker(fail_max=5, reset_timeout=30)
        self._agent_token: str | None = None
        self._agent_token_expiry: float = 0.0

    def _get_agent_token(self) -> str:
        if self._agent_token and time.time() < self._agent_token_expiry - 30:
            return self._agent_token
        response = self._http.post(
            "/auth/token",
            json={
                "grant_type": "client_credentials",
                "client_id": mcp_settings.agent_client_id,
                "client_secret": mcp_settings.agent_client_secret,
            },
        )
        response.raise_for_status()
        body = response.json()
        self._agent_token = body["access_token"]
        self._agent_token_expiry = time.time() + body["expires_in"]
        return self._agent_token

    def _raw_call(self, method: str, path: str, headers: dict, **kwargs) -> httpx.Response:
        response = self._http.request(method, path, headers=headers, **kwargs)
        if response.status_code >= 500:
            response.raise_for_status()
        return response

    def _request(self, method: str, path: str, headers: dict | None = None, **kwargs) -> dict:
        all_headers = {
            "X-Agent-Token": self._get_agent_token(),
            "Authorization": f"Bearer {mcp_settings.customer_token}",
            "X-Correlation-ID": str(uuid.uuid4()),
            **(headers or {}),
        }
        try:
            response = self.circuit_breaker.call(
                self._raw_call, method, path, all_headers, **kwargs
            )
        except pybreaker.CircuitBreakerError as exc:
            raise BankingAPIError("Banking service temporarily unavailable.") from exc
        except httpx.HTTPStatusError as exc:
            raise BankingAPIError(
                f"Banking API returned {exc.response.status_code}.",
                status_code=exc.response.status_code,
            ) from exc

        if response.status_code >= 400:
            body = response.json() if response.content else {}
            error = body.get("error", {})
            raise BankingAPIError(
                error.get("message", f"HTTP {response.status_code}"),
                status_code=response.status_code,
                code=error.get("code"),
            )
        return response.json()

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(multiplier=0.1, max=1),
        reraise=True,
    )
    def get(self, path: str, params: dict | None = None) -> dict:
        return self._request("GET", path, params=params)

    @retry(
        retry=retry_if_exception(_is_retryable),
        stop=stop_after_attempt(3),
        wait=wait_exponential_jitter(multiplier=0.1, max=1),
        reraise=True,
    )
    def post(self, path: str, json_body: dict, idempotency_key: str | None = None) -> dict:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._request("POST", path, headers=headers, json=json_body)
