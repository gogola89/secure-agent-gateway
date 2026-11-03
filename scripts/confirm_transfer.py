"""`make confirm TRANSFER=<id> OTP=<code>` - simulates the customer's own
mobile app: logs in fresh as the customer (full scopes, including
`transfers:confirm`) and calls the confirm endpoint directly, with no
agent token at all. This is the channel the AI agent has no tool for.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from banking_api.config import settings  # noqa: E402
from scripts.login import BANKING_API_URL, CUSTOMER_PHONES  # noqa: E402


def main() -> None:
    if len(sys.argv) < 4 or sys.argv[1] not in CUSTOMER_PHONES:
        names = ", ".join(CUSTOMER_PHONES)
        print(f"Usage: make confirm CUSTOMER=<{names}> TRANSFER=<id> OTP=<code>")
        raise SystemExit(1)

    customer, transfer_id, otp = sys.argv[1], sys.argv[2], sys.argv[3]
    phone = CUSTOMER_PHONES[customer]

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
        app_token = login_resp.json()["access_token"]

        confirm_resp = client.post(
            f"/transfers/{transfer_id}/confirm",
            json={"otp": otp},
            headers={"Authorization": f"Bearer {app_token}"},
        )

    print(confirm_resp.status_code, confirm_resp.json())


if __name__ == "__main__":
    main()
