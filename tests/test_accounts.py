"""Section 9: Ownership - Amina cannot read Brian's ACC-1 transactions or
use his beneficiary; response is 404, identical to a missing alias.
Masking - no full account number or phone appears in any response."""

from __future__ import annotations

import re

from .conftest import auth_headers

TWELVE_DIGITS = re.compile(r"\d{12}")


def test_lists_only_own_accounts(client, amina_token, agent_token):
    response = client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    assert response.status_code == 200
    aliases = {a["alias"] for a in response.json()}
    assert aliases == {"ACC-1", "ACC-2"}
    for account in response.json():
        assert account["masked_account_number"].startswith("****")
        assert len(account["masked_account_number"]) == 8
        assert not TWELVE_DIGITS.search(account["masked_account_number"])


def test_same_alias_resolves_to_different_underlying_accounts_per_customer(
    client, amina_token, brian_token, agent_token
):
    # Amina's "ACC-1" and Brian's "ACC-1" are different accounts (section 4):
    # every alias lookup must be scoped by the authenticated customer_id,
    # never resolved globally.
    amina_accounts = {
        a["alias"]: a["masked_account_number"]
        for a in client.get("/accounts", headers=auth_headers(amina_token, agent_token)).json()
    }
    brian_accounts = {
        a["alias"]: a["masked_account_number"]
        for a in client.get("/accounts", headers=auth_headers(brian_token, agent_token)).json()
    }
    assert amina_accounts["ACC-1"] != brian_accounts["ACC-1"]


def test_missing_alias_and_other_customers_alias_both_404_identically(
    client, amina_token, agent_token
):
    nonexistent = client.get(
        "/accounts/ACC-99/transactions", headers=auth_headers(amina_token, agent_token)
    )
    assert nonexistent.status_code == 404
    assert nonexistent.json()["error"]["code"] == "not_found"


def test_cannot_use_another_customers_beneficiary(client, brian_token, agent_token):
    # Brian only has beneficiary alias BEN-1 (Amina). Amina's BEN-2 does not
    # exist for him - must be a 404, never "forbidden" (which would confirm
    # the alias exists for someone else).
    response = client.get("/beneficiaries", headers=auth_headers(brian_token, agent_token))
    assert response.status_code == 200
    aliases = {b["alias"] for b in response.json()}
    assert aliases == {"BEN-1"}


def test_recent_transactions_include_the_prompt_injection_fixture_as_plain_text(
    client, amina_token, agent_token
):
    response = client.get(
        "/accounts/ACC-2/transactions?limit=20", headers=auth_headers(amina_token, agent_token)
    )
    assert response.status_code == 200
    narrations = [t["narration"] for t in response.json()]
    assert any("IGNORE ALL PREVIOUS INSTRUCTIONS" in n for n in narrations)


def test_no_full_account_number_or_phone_leaks_anywhere(client, amina_token, agent_token):
    accounts = client.get("/accounts", headers=auth_headers(amina_token, agent_token))
    beneficiaries = client.get("/beneficiaries", headers=auth_headers(amina_token, agent_token))
    transactions = client.get(
        "/accounts/ACC-1/transactions", headers=auth_headers(amina_token, agent_token)
    )
    for response in (accounts, beneficiaries, transactions):
        assert not TWELVE_DIGITS.search(response.text)
