from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from banking_api.auth import EffectivePrincipal, require_scopes
from banking_api.authz import get_owned_account
from banking_api.db import get_db
from banking_api.masking import mask_account_number
from banking_api.models import Account, Beneficiary, Transaction
from banking_api.ratelimit import rate_limit_reads
from banking_api.schemas import (
    AccountOut,
    BeneficiaryOut,
    TransactionOut,
    amount_cents_to_kes,
)

router = APIRouter(tags=["accounts"], dependencies=[Depends(rate_limit_reads)])

require_accounts_read = require_scopes("accounts:read")
require_transactions_read = require_scopes("transactions:read")


@router.get("/accounts", response_model=list[AccountOut])
def list_accounts(
    principal: EffectivePrincipal = Depends(require_accounts_read),
    db: Session = Depends(get_db),
) -> list[AccountOut]:
    accounts = (
        db.query(Account).filter_by(customer_id=principal.customer_id).order_by(Account.alias)
    )
    return [
        AccountOut(
            alias=a.alias,
            type=a.type,
            masked_account_number=mask_account_number(a.account_number),
            balance_kes=amount_cents_to_kes(a.balance_cents),
            currency=a.currency,
        )
        for a in accounts
    ]


@router.get("/accounts/{alias}/transactions", response_model=list[TransactionOut])
def get_recent_transactions(
    alias: str,
    limit: int = Query(default=10, ge=1, le=20),
    principal: EffectivePrincipal = Depends(require_transactions_read),
    db: Session = Depends(get_db),
) -> list[TransactionOut]:
    account = get_owned_account(db, principal.customer_id, alias)
    transactions = (
        db.query(Transaction)
        .filter_by(account_id=account.id)
        .order_by(Transaction.posted_at.desc())
        .limit(limit)
    )
    return [
        TransactionOut(
            posted_at=t.posted_at,
            amount_kes=amount_cents_to_kes(t.amount_cents),
            narration=t.narration,
            reference=t.reference,
        )
        for t in transactions
    ]


@router.get("/beneficiaries", response_model=list[BeneficiaryOut])
def list_beneficiaries(
    principal: EffectivePrincipal = Depends(require_accounts_read),
    db: Session = Depends(get_db),
) -> list[BeneficiaryOut]:
    beneficiaries = (
        db.query(Beneficiary)
        .filter_by(customer_id=principal.customer_id)
        .order_by(Beneficiary.alias)
    )
    return [
        BeneficiaryOut(
            alias=b.alias,
            name=b.name,
            bank_name=b.bank_name,
            masked_account_number=mask_account_number(b.account_number),
        )
        for b in beneficiaries
    ]
