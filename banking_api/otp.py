"""OTP generation, storage and verification for the human-in-the-loop
confirmation step (section 7). The OTP itself is only ever handed to the
customer's own channel (the mock SMS outbox) - never returned to the
agent in any API response, which is the whole point of this step."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from pathlib import Path

import redis as redis_lib

from banking_api.config import settings
from banking_api.masking import mask_phone

ATTEMPTS_SUFFIX = ":attempts"


def _hash_key(transfer_id: str) -> str:
    return f"otp:{transfer_id}"


def _attempts_key(transfer_id: str) -> str:
    return f"otp:{transfer_id}{ATTEMPTS_SUFFIX}"


def generate_otp() -> str:
    return f"{secrets.randbelow(1_000_000):06d}"


def store_otp(redis_client: redis_lib.Redis, transfer_id: str, otp: str) -> None:
    hashed = hashlib.sha256(otp.encode()).hexdigest()
    redis_client.set(_hash_key(transfer_id), hashed, ex=settings.otp_ttl_seconds)
    redis_client.set(_attempts_key(transfer_id), 0, ex=settings.otp_ttl_seconds)


def send_otp_sms(phone: str, otp: str) -> None:
    path = Path(settings.sms_outbox_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC).isoformat()
    line = f"[{timestamp}] To {mask_phone(phone)}: your OTP is {otp}. Valid for 5 minutes.\n"
    with path.open("a") as f:
        f.write(line)


def clear_otp(redis_client: redis_lib.Redis, transfer_id: str) -> None:
    redis_client.delete(_hash_key(transfer_id), _attempts_key(transfer_id))


def check_otp(redis_client: redis_lib.Redis, transfer_id: str, otp: str) -> str:
    """Returns one of: "ok", "incorrect", "exceeded", "missing" (expired or
    never issued - treated the same as expired by the caller)."""
    stored_hash = redis_client.get(_hash_key(transfer_id))
    if stored_hash is None:
        return "missing"

    if hashlib.sha256(otp.encode()).hexdigest() == stored_hash:
        return "ok"

    attempts = redis_client.incr(_attempts_key(transfer_id))
    if attempts >= settings.otp_max_attempts:
        return "exceeded"
    return "incorrect"
