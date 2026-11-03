"""Section 9: contract testing.

1. OpenAPI drift (`make openapi` vs the committed `openapi.json`) is
   checked in CI, not here - see `.github/workflows/ci.yml`.
2. This file is the second layer: validate real responses from key
   endpoints against the committed schema with `openapi-core`, so a
   response that silently drifted from its own documented shape (not just
   a code smell `ruff`/types would catch) fails the suite.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from openapi_core import OpenAPI
from openapi_core.datatypes import RequestParameters

from .conftest import auth_headers

SPEC_PATH = Path(__file__).resolve().parent.parent / "openapi.json"
openapi_spec = OpenAPI.from_file_path(str(SPEC_PATH))


@dataclass
class _SimpleOpenAPIRequest:
    method: str
    path: str
    host_url: str = "http://testserver"
    body: bytes | None = None
    content_type: str = "application/json"
    parameters: RequestParameters = field(default_factory=RequestParameters)


class _HttpxOpenAPIResponse:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    @property
    def status_code(self) -> int:
        return self._response.status_code

    @property
    def content_type(self) -> str:
        return self._response.headers.get("content-type", "application/json")

    @property
    def headers(self) -> Mapping[str, str]:
        return self._response.headers

    @property
    def data(self) -> bytes | None:
        return self._response.content


def assert_matches_contract(method: str, path: str, response: httpx.Response) -> None:
    request = _SimpleOpenAPIRequest(method=method.lower(), path=path)
    openapi_spec.validate_response(request, _HttpxOpenAPIResponse(response))


def test_accounts_response_matches_contract(client, amina_token, agent_token):
    response = client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    assert_matches_contract("get", "/accounts", response)


def test_denied_response_matches_contract(client):
    response = client.get("/accounts")
    assert_matches_contract("get", "/accounts", response)


def test_transfer_not_found_response_matches_contract(client, amina_token, agent_token):
    response = client.get(
        "/transfers/00000000-0000-0000-0000-000000000000",
        headers=auth_headers(amina_token, agent_token),
    )
    assert_matches_contract("get", "/transfers/{transfer_id}", response)


def test_token_response_matches_contract(client):
    response = client.post(
        "/auth/token",
        json={"grant_type": "password", "username": "+254712345000", "password": "wrong"},
    )
    assert_matches_contract("post", "/auth/token", response)
