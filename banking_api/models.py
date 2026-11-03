"""SQLAlchemy models for the mock system of record.

Money is always integer cents (`*_cents`) to avoid floating-point errors.
Timestamps are UTC. Primary keys use a GUID type that is a native UUID on
Postgres and a CHAR(36) on SQLite, so the same models run against the real
database and the fast in-memory tests (section 4 of the build spec)."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import CHAR, JSON, TypeDecorator

from banking_api.db import Base


class GUID(TypeDecorator):
    """Platform-independent UUID: native UUID on Postgres, CHAR(36) elsewhere."""

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PG_UUID(as_uuid=True))
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        if dialect.name == "postgresql":
            return str(value)
        return str(value) if isinstance(value, uuid.UUID) else value

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONVariant(TypeDecorator):
    """JSONB on Postgres, plain JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


def new_uuid() -> uuid.UUID:
    return uuid.uuid4()


class Customer(Base):
    __tablename__ = "customers"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str] = mapped_column(String(20), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    accounts: Mapped[list[Account]] = relationship(back_populates="customer")
    beneficiaries: Mapped[list[Beneficiary]] = relationship(back_populates="customer")


class Account(Base):
    __tablename__ = "accounts"
    __table_args__ = (UniqueConstraint("customer_id", "alias", name="uq_account_customer_alias"),)

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id"), nullable=False
    )
    account_number: Mapped[str] = mapped_column(String(12), nullable=False, unique=True)
    alias: Mapped[str] = mapped_column(String(20), nullable=False)
    type: Mapped[str] = mapped_column(String(20), nullable=False)
    balance_cents: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="KES")

    customer: Mapped[Customer] = relationship(back_populates="accounts")
    transactions: Mapped[list[Transaction]] = relationship(back_populates="account")


class Beneficiary(Base):
    __tablename__ = "beneficiaries"
    __table_args__ = (
        UniqueConstraint("customer_id", "alias", name="uq_beneficiary_customer_alias"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    bank_name: Mapped[str] = mapped_column(String(120), nullable=False)
    account_number: Mapped[str] = mapped_column(String(20), nullable=False)
    alias: Mapped[str] = mapped_column(String(20), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="beneficiaries")


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    account_id: Mapped[uuid.UUID] = mapped_column(GUID(), ForeignKey("accounts.id"), nullable=False)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    narration: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    account: Mapped[Account] = relationship(back_populates="transactions")


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (
        UniqueConstraint("customer_id", "idempotency_key", name="uq_transfer_customer_idemkey"),
        CheckConstraint("amount_cents > 0", name="ck_transfer_amount_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id"), nullable=False
    )
    from_account_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("accounts.id"), nullable=False
    )
    beneficiary_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("beneficiaries.id"), nullable=False
    )
    amount_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    narration: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending_confirmation")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(60), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    correlation_id: Mapped[str] = mapped_column(String(64), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(60), nullable=True)
    customer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    args_masked: Mapped[dict] = mapped_column(JSONVariant(), nullable=False, default=dict)
    decision: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    row_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class Outbox(Base):
    __tablename__ = "outbox"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    event_type: Mapped[str] = mapped_column(String(60), nullable=False)
    payload: Mapped[dict] = mapped_column(JSONVariant(), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(GUID(), primary_key=True, default=new_uuid)
    transfer_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, unique=True)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    message: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


__all__ = [
    "Account",
    "AuditLog",
    "Beneficiary",
    "Customer",
    "Notification",
    "Outbox",
    "Transaction",
    "Transfer",
]
