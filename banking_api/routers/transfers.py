"""Transfer initiation and confirmation (section 7). A transfer has two
halves: the agent creates it (`transfers:initiate`), and only the customer,
through their own app and a separate OTP channel, can complete it
(`transfers:confirm` - a scope the agent token can never hold, see
`banking_api.auth.SCOPES_NEVER_DELEGATED`)."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from banking_api.auth import Principal, get_customer_principal, require_scopes
from banking_api.authz import get_owned_account, get_owned_beneficiary
from banking_api.config import settings
from banking_api.db import get_db
from banking_api.errors import AppError, error_responses
from banking_api.models import Account, Customer, Transaction, Transfer
from banking_api.otp import check_otp, clear_otp, generate_otp, send_otp_sms, store_otp
from banking_api.ratelimit import rate_limit_reads, rate_limit_transfers
from banking_api.redis_client import get_redis
from banking_api.rules import validate_transfer
from banking_api.schemas import ConfirmRequest, TransferCreate, TransferOut, amount_kes_to_cents

router = APIRouter(prefix="/transfers", tags=["transfers"], responses=error_responses(401, 403))

require_transfers_initiate = require_scopes("transfers:initiate")

MIN_IDEMPOTENCY_KEY_LENGTH = 8
MAX_IDEMPOTENCY_KEY_LENGTH = 128


def _canonical_request_hash(body: TransferCreate) -> str:
    canonical = json.dumps(body.model_dump(), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _transfer_out(transfer: Transfer, message: str | None = None) -> TransferOut:
    expires_at = None
    if transfer.status == "pending_confirmation":
        expires_at = transfer.created_at + timedelta(seconds=settings.otp_ttl_seconds)
    return TransferOut(
        transfer_id=str(transfer.id),
        status=transfer.status,
        expires_at=expires_at,
        created_at=transfer.created_at,
        confirmed_at=transfer.confirmed_at,
        message=message,
    )


@router.post(
    "",
    response_model=TransferOut,
    status_code=201,
    dependencies=[Depends(rate_limit_transfers)],
    responses=error_responses(400, 404, 409, 422, 429),
)
def initiate_transfer(
    body: TransferCreate,
    response: Response,
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    principal=Depends(require_transfers_initiate),
    db: Session = Depends(get_db),
) -> TransferOut:
    if not (MIN_IDEMPOTENCY_KEY_LENGTH <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY_LENGTH):
        raise AppError(
            400,
            "invalid_idempotency_key",
            f"Idempotency-Key must be {MIN_IDEMPOTENCY_KEY_LENGTH} to "
            f"{MAX_IDEMPOTENCY_KEY_LENGTH} characters.",
        )

    request_hash = _canonical_request_hash(body)

    existing = (
        db.query(Transfer)
        .filter_by(customer_id=principal.customer_id, idempotency_key=idempotency_key)
        .one_or_none()
    )
    if existing is not None:
        return _replay_or_conflict(existing, request_hash, response)

    from_account = get_owned_account(db, principal.customer_id, body.from_account_alias)
    beneficiary = get_owned_beneficiary(db, principal.customer_id, body.beneficiary_alias)
    amount_cents = amount_kes_to_cents(body.amount_kes)

    validate_transfer(db, principal.customer_id, from_account, amount_cents)

    transfer = Transfer(
        id=uuid.uuid4(),
        customer_id=principal.customer_id,
        from_account_id=from_account.id,
        beneficiary_id=beneficiary.id,
        amount_cents=amount_cents,
        narration=body.narration,
        status="pending_confirmation",
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        agent_id=principal.agent_id,
    )
    db.add(transfer)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = (
            db.query(Transfer)
            .filter_by(customer_id=principal.customer_id, idempotency_key=idempotency_key)
            .one()
        )
        return _replay_or_conflict(existing, request_hash, response)

    db.refresh(transfer)
    customer = db.get(Customer, principal.customer_id)
    otp = generate_otp()
    store_otp(get_redis(), str(transfer.id), otp)
    send_otp_sms(customer.phone, otp)

    return _transfer_out(
        transfer,
        message="Ask the customer to confirm this transfer with the OTP sent to their phone.",
    )


def _replay_or_conflict(existing: Transfer, request_hash: str, response: Response) -> TransferOut:
    if existing.request_hash != request_hash:
        raise AppError(
            409, "idempotency_key_reuse", "Idempotency-Key reused with a different request."
        )
    response.status_code = 200
    response.headers["Idempotent-Replay"] = "true"
    return _transfer_out(existing)


@router.get(
    "/{transfer_id}",
    response_model=TransferOut,
    dependencies=[Depends(rate_limit_reads)],
    responses=error_responses(404, 429),
)
def get_transfer_status(
    transfer_id: str,
    principal=Depends(require_transfers_initiate),
    db: Session = Depends(get_db),
) -> TransferOut:
    transfer = (
        db.query(Transfer)
        .filter_by(id=transfer_id, customer_id=principal.customer_id)
        .one_or_none()
    )
    if transfer is None:
        raise AppError(404, "not_found", "No such transfer for this customer.")
    return _transfer_out(transfer)


@router.post(
    "/{transfer_id}/confirm",
    response_model=TransferOut,
    responses=error_responses(404, 409, 422),
)
def confirm_transfer(
    transfer_id: str,
    body: ConfirmRequest,
    x_agent_token: str | None = Header(default=None, alias="X-Agent-Token"),
    principal: Principal = Depends(get_customer_principal),
    db: Session = Depends(get_db),
) -> TransferOut:
    if x_agent_token is not None:
        raise AppError(403, "agents_cannot_confirm", "Agents cannot confirm transfers.")
    if "transfers:confirm" not in principal.scopes:
        raise AppError(
            403,
            "forbidden",
            "scope_missing:transfers:confirm",
            audit_reason="scope_missing:transfers:confirm",
        )

    transfer = db.query(Transfer).filter_by(id=transfer_id, customer_id=principal.sub).one_or_none()
    if transfer is None:
        raise AppError(404, "not_found", "No such transfer for this customer.")

    if transfer.status == "completed":
        return _transfer_out(transfer)
    if transfer.status in ("rejected", "expired", "failed"):
        raise AppError(
            409, f"transfer_{transfer.status}", f"Transfer is already {transfer.status}."
        )

    expiry = transfer.created_at + timedelta(seconds=settings.otp_ttl_seconds)
    if datetime.now(UTC) >= expiry:
        transfer.status = "expired"
        db.commit()
        clear_otp(get_redis(), str(transfer.id))
        raise AppError(409, "transfer_expired", "The OTP for this transfer has expired.")

    result = check_otp(get_redis(), str(transfer.id), body.otp)
    if result == "missing":
        transfer.status = "expired"
        db.commit()
        raise AppError(409, "transfer_expired", "The OTP for this transfer has expired.")
    if result == "exceeded":
        transfer.status = "rejected"
        db.commit()
        clear_otp(get_redis(), str(transfer.id))
        raise AppError(409, "otp_max_attempts_exceeded", "Too many incorrect OTP attempts.")
    if result == "incorrect":
        raise AppError(401, "otp_incorrect", "Incorrect OTP.")

    from_account = db.get(Account, transfer.from_account_id)
    validate_transfer(db, principal.sub, from_account, transfer.amount_cents)

    from_account.balance_cents -= transfer.amount_cents
    db.add(
        Transaction(
            id=uuid.uuid4(),
            account_id=from_account.id,
            amount_cents=-transfer.amount_cents,
            narration=f"Transfer: {transfer.narration}",
            reference=f"XFER-{uuid.uuid4().hex[:10].upper()}",
        )
    )
    transfer.status = "completed"
    transfer.confirmed_at = datetime.now(UTC)
    db.commit()
    db.refresh(transfer)
    clear_otp(get_redis(), str(transfer.id))

    return _transfer_out(transfer)
