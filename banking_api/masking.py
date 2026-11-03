"""Masking helpers, used identically by API responses, audit rows and logs
so no code path can accidentally leak a full account number or phone."""

from __future__ import annotations


def mask_account_number(account_number: str) -> str:
    return "****" + account_number[-4:]


def mask_phone(phone: str) -> str:
    """+254712345000 -> +2547****5000"""
    return phone[:5] + "****" + phone[-4:]
