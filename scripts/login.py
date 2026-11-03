"""`make login CUSTOMER=amina` - logs in as a seeded customer, then performs
a token-exchange (RFC 8693 style) to narrow the token to what the MCP
server is allowed to hold: the customer's scopes minus `transfers:confirm`.
Writes the result into CUSTOMER_TOKEN in .env for the MCP server to read.

Requires the banking API to be running (`make run-api` or the `api`
Docker Compose service).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from banking_api.config import settings  # noqa: E402

CUSTOMER_PHONES = {
    "amina": "+254712345000",
    "brian": "+254723456000",
}

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"
BANKING_API_URL = os.environ.get("BANKING_API_URL", "http://localhost:8000")
AGENT_CLIENT_ID = os.environ.get("AGENT_CLIENT_ID", "assistant-v1")


def write_customer_token(token: str) -> None:
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    found = False
    for i, line in enumerate(lines):
        if line.startswith("CUSTOMER_TOKEN="):
            lines[i] = f"CUSTOMER_TOKEN={token}"
            found = True
            break
    if not found:
        lines.append(f"CUSTOMER_TOKEN={token}")
    ENV_PATH.write_text("\n".join(lines) + "\n")


def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in CUSTOMER_PHONES:
        names = ", ".join(CUSTOMER_PHONES)
        print(f"Usage: make login CUSTOMER=<{names}>")
        raise SystemExit(1)

    phone = CUSTOMER_PHONES[sys.argv[1]]

    with httpx.Client(base_url=BANKING_API_URL, timeout=5.0) as client:
        login_resp = client.post(
            "/auth/token",
            json={
                "grant_type": "password",
                "username": phone,
                "password": settings.demo_customer_password,
            },
        )
        login_resp.raise_for_status()
        full_token = login_resp.json()["access_token"]

        exchange_resp = client.post(
            "/auth/token",
            json={
                "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
                "subject_token": full_token,
                "client_id": AGENT_CLIENT_ID,
            },
        )
        exchange_resp.raise_for_status()
        delegated = exchange_resp.json()

    write_customer_token(delegated["access_token"])
    print(f"Delegated token for '{sys.argv[1]}' written to .env (CUSTOMER_TOKEN).")
    print(f"Scopes: {delegated['scope']}")


if __name__ == "__main__":
    main()
