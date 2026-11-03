"""Transfer business rules (section 7): amount bounds, the daily cap, and
available balance. Kept separate from the route handler so the numbers
that matter for a banking demo are easy to find and explain on their own.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from banking_api.config import settings
from banking_api.errors import AppError
from banking_api.models import Account, Transfer

ACTIVE_TRANSFER_STATUSES = ("pending_confirmation", "completed")


def _start_of_today_utc() -> datetime:
    now = datetime.now(UTC)
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def validate_transfer(
    db: Session, customer_id: str, from_account: Account, amount_cents: int
) -> None:
    if amount_cents <= 0:
        raise AppError(422, "invalid_amount", "amount_kes must be greater than zero.")

    if amount_cents > settings.transfer_max_amount_cents:
        raise AppError(
            422,
            "amount_exceeds_limit",
            f"amount_kes exceeds the per-transfer limit of "
            f"{settings.transfer_max_amount_cents / 100:.2f} KES.",
        )

    daily_total = (
        db.query(func.coalesce(func.sum(Transfer.amount_cents), 0))
        .filter(
            Transfer.customer_id == customer_id,
            Transfer.status.in_(ACTIVE_TRANSFER_STATUSES),
            Transfer.created_at >= _start_of_today_utc(),
        )
        .scalar()
    )
    if daily_total + amount_cents > settings.transfer_daily_limit_cents:
        raise AppError(
            422,
            "daily_limit_exceeded",
            f"This transfer would exceed the daily limit of "
            f"{settings.transfer_daily_limit_cents / 100:.2f} KES.",
        )

    pending_from_account = (
        db.query(func.coalesce(func.sum(Transfer.amount_cents), 0))
        .filter(
            Transfer.from_account_id == from_account.id,
            Transfer.status == "pending_confirmation",
        )
        .scalar()
    )
    available_cents = from_account.balance_cents - pending_from_account
    if available_cents < amount_cents:
        raise AppError(422, "insufficient_balance", "Insufficient available balance.")
