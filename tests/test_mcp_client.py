"""Section 9: MCP client - circuit breaker opens after 5 failures; GET
retries happen; POST retry reuses the same Idempotency-Key (respx mocks)."""

from __future__ import annotations

import httpx
import pytest
import respx

from mcp_server.client import BankingAPIClient, BankingAPIError

BASE_URL = "http://test-banking-api"


def _mock_token_route(router: respx.MockRouter) -> None:
    router.post(f"{BASE_URL}/auth/token").mock(
        return_value=httpx.Response(
            200, json={"access_token": "fake-agent-token", "expires_in": 900}
        )
    )


@pytest.fixture
def client() -> BankingAPIClient:
    c = BankingAPIClient()
    c._http = httpx.Client(base_url=BASE_URL)
    return c


@respx.mock
def test_get_retries_on_server_errors_then_succeeds(client):
    _mock_token_route(respx)
    route = respx.get(f"{BASE_URL}/accounts").mock(
        side_effect=[
            httpx.Response(500, json={"error": {"code": "internal_error", "message": "boom"}}),
            httpx.Response(500, json={"error": {"code": "internal_error", "message": "boom"}}),
            httpx.Response(200, json=[{"alias": "ACC-1"}]),
        ]
    )
    result = client.get("/accounts")
    assert result == [{"alias": "ACC-1"}]
    assert route.call_count == 3


@respx.mock
def test_get_does_not_retry_on_client_errors(client):
    _mock_token_route(respx)
    route = respx.get(f"{BASE_URL}/accounts/ACC-99/transactions").mock(
        return_value=httpx.Response(404, json={"error": {"code": "not_found", "message": "no"}})
    )
    with pytest.raises(BankingAPIError) as exc_info:
        client.get("/accounts/ACC-99/transactions")
    assert exc_info.value.status_code == 404
    assert route.call_count == 1


@respx.mock
def test_post_retry_reuses_the_same_idempotency_key(client):
    _mock_token_route(respx)
    route = respx.post(f"{BASE_URL}/transfers").mock(
        side_effect=[
            httpx.Response(500, json={"error": {"code": "internal_error", "message": "boom"}}),
            httpx.Response(201, json={"transfer_id": "abc", "status": "pending_confirmation"}),
        ]
    )
    result = client.post("/transfers", {"amount_kes": "100.00"}, idempotency_key="fixed-key-123")
    assert result["transfer_id"] == "abc"
    assert route.call_count == 2
    keys_used = {call.request.headers["Idempotency-Key"] for call in route.calls}
    assert keys_used == {"fixed-key-123"}


@respx.mock
def test_circuit_breaker_opens_after_repeated_failures(client):
    _mock_token_route(respx)
    respx.get(f"{BASE_URL}/accounts").mock(
        return_value=httpx.Response(
            500, json={"error": {"code": "internal_error", "message": "boom"}}
        )
    )

    last_error = None
    for _ in range(4):
        try:
            client.get("/accounts")
        except BankingAPIError as exc:
            last_error = exc

    assert client.circuit_breaker.current_state == "open"
    assert last_error is not None
    assert "temporarily unavailable" in str(last_error) or last_error.status_code == 500
