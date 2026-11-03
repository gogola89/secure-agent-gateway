from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pydantic import BaseModel, ConfigDict, field_validator

AMOUNT_RE = re.compile(r"^\d{1,9}(\.\d{1,2})?$")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


# --- Auth ---


class TokenRequest(StrictModel):
    grant_type: str
    username: str | None = None
    password: str | None = None
    client_id: str | None = None
    client_secret: str | None = None
    subject_token: str | None = None


class TokenResponse(StrictModel):
    access_token: str
    token_type: str = "Bearer"
    expires_in: int
    scope: str


# --- Accounts / transactions / beneficiaries ---


class AccountOut(StrictModel):
    alias: str
    type: str
    masked_account_number: str
    balance_kes: str
    currency: str


class TransactionOut(StrictModel):
    posted_at: datetime
    amount_kes: str
    narration: str
    reference: str


class BeneficiaryOut(StrictModel):
    alias: str
    name: str
    bank_name: str
    masked_account_number: str


# --- Transfers ---


class TransferCreate(StrictModel):
    from_account_alias: str
    beneficiary_alias: str
    amount_kes: str
    narration: str

    @field_validator("amount_kes")
    @classmethod
    def validate_amount(cls, value: str) -> str:
        if not AMOUNT_RE.match(value):
            raise ValueError("amount_kes must be a decimal string with at most 2 places")
        try:
            Decimal(value)
        except InvalidOperation as exc:
            raise ValueError("amount_kes is not a valid number") from exc
        return value

    @field_validator("narration")
    @classmethod
    def validate_narration(cls, value: str) -> str:
        if len(value) > 60:
            raise ValueError("narration must be at most 60 characters")
        if not value.isprintable():
            raise ValueError("narration must contain only printable characters")
        return value


class TransferOut(StrictModel):
    transfer_id: str
    status: str
    expires_at: datetime | None = None
    created_at: datetime
    confirmed_at: datetime | None = None
    message: str | None = None


class ConfirmRequest(StrictModel):
    otp: str

    @field_validator("otp")
    @classmethod
    def validate_otp(cls, value: str) -> str:
        if not re.fullmatch(r"\d{6}", value):
            raise ValueError("otp must be 6 digits")
        return value


def amount_cents_to_kes(amount_cents: int) -> str:
    sign = "-" if amount_cents < 0 else ""
    cents = abs(amount_cents)
    return f"{sign}{cents // 100}.{cents % 100:02d}"


def amount_kes_to_cents(amount_kes: str) -> int:
    return int((Decimal(amount_kes) * 100).to_integral_value())
