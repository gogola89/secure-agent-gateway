"""Object-level authorisation: every account or beneficiary is resolved by
alias *scoped to the authenticated customer_id*. Not found and not owned
both return the identical 404, so the API never confirms to a caller that
another customer's alias even exists (section 5)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from banking_api.errors import AppError
from banking_api.models import Account, Beneficiary


def _not_found_reason(db: Session, model, customer_id: str, alias: str) -> str:
    """Public response is the identical 404 either way; only the audit
    trail learns whether the alias belongs to someone else."""
    exists_elsewhere = (
        db.query(model.id).filter_by(alias=alias).filter(model.customer_id != customer_id).first()
        is not None
    )
    return "not_owner" if exists_elsewhere else "not_found"


def get_owned_account(db: Session, customer_id: str, alias: str) -> Account:
    account = db.query(Account).filter_by(customer_id=customer_id, alias=alias).one_or_none()
    if account is None:
        reason = _not_found_reason(db, Account, customer_id, alias)
        raise AppError(
            404, "not_found", f"No account '{alias}' for this customer.", audit_reason=reason
        )
    return account


def get_owned_beneficiary(db: Session, customer_id: str, alias: str) -> Beneficiary:
    beneficiary = (
        db.query(Beneficiary).filter_by(customer_id=customer_id, alias=alias).one_or_none()
    )
    if beneficiary is None:
        reason = _not_found_reason(db, Beneficiary, customer_id, alias)
        raise AppError(
            404, "not_found", f"No beneficiary '{alias}' for this customer.", audit_reason=reason
        )
    return beneficiary
