"""Object-level authorisation: every account or beneficiary is resolved by
alias *scoped to the authenticated customer_id*. Not found and not owned
both return the identical 404, so the API never confirms to a caller that
another customer's alias even exists (section 5)."""

from __future__ import annotations

from sqlalchemy.orm import Session

from banking_api.errors import AppError
from banking_api.models import Account, Beneficiary


def get_owned_account(db: Session, customer_id: str, alias: str) -> Account:
    account = db.query(Account).filter_by(customer_id=customer_id, alias=alias).one_or_none()
    if account is None:
        raise AppError(404, "not_found", f"No account '{alias}' for this customer.")
    return account


def get_owned_beneficiary(db: Session, customer_id: str, alias: str) -> Beneficiary:
    beneficiary = (
        db.query(Beneficiary).filter_by(customer_id=customer_id, alias=alias).one_or_none()
    )
    if beneficiary is None:
        raise AppError(404, "not_found", f"No beneficiary '{alias}' for this customer.")
    return beneficiary
