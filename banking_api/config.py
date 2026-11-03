"""Settings loaded from environment variables. No framework config magic:
the whole project is small enough that explicit os.environ reads, with
defaults for local dev, are easier to audit than a settings library."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _getenv_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    return int(value) if value else default


def _getenv_list(name: str, default: str) -> list[str]:
    value = os.environ.get(name, default)
    return [scope for scope in value.split() if scope]


@dataclass(frozen=True)
class AgentCredentials:
    client_id: str
    client_secret: str
    scopes: list[str]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(
        default_factory=lambda: os.environ.get(
            "DATABASE_URL",
            "postgresql+psycopg://gateway:gateway@localhost:5432/gateway",
        )
    )
    redis_url: str = field(
        default_factory=lambda: os.environ.get("REDIS_URL", "redis://localhost:6379/0")
    )
    rabbitmq_url: str = field(
        default_factory=lambda: os.environ.get("RABBITMQ_URL", "amqp://guest:guest@localhost:5672/")
    )

    jwt_private_key_path: str = field(
        default_factory=lambda: os.environ.get("JWT_PRIVATE_KEY_PATH", "keys/private.pem")
    )
    jwt_public_key_path: str = field(
        default_factory=lambda: os.environ.get("JWT_PUBLIC_KEY_PATH", "keys/public.pem")
    )
    jwt_issuer: str = field(default_factory=lambda: os.environ.get("JWT_ISSUER", "mock-idp"))
    jwt_audience: str = field(default_factory=lambda: os.environ.get("JWT_AUDIENCE", "banking-api"))
    jwt_access_token_ttl_seconds: int = field(
        default_factory=lambda: _getenv_int("JWT_ACCESS_TOKEN_TTL_SECONDS", 900)
    )

    demo_customer_password: str = field(
        default_factory=lambda: os.environ.get("DEMO_CUSTOMER_PASSWORD", "demo-password")
    )
    admin_token: str = field(
        default_factory=lambda: os.environ.get("ADMIN_TOKEN", "local-admin-token")
    )

    transfer_max_amount_cents: int = field(
        default_factory=lambda: _getenv_int("TRANSFER_MAX_AMOUNT_CENTS", 100_000 * 100)
    )
    transfer_daily_limit_cents: int = field(
        default_factory=lambda: _getenv_int("TRANSFER_DAILY_LIMIT_CENTS", 150_000 * 100)
    )
    otp_ttl_seconds: int = field(default_factory=lambda: _getenv_int("OTP_TTL_SECONDS", 300))
    otp_max_attempts: int = field(default_factory=lambda: _getenv_int("OTP_MAX_ATTEMPTS", 3))

    rate_limit_reads_per_minute: int = field(
        default_factory=lambda: _getenv_int("RATE_LIMIT_READS_PER_MINUTE", 30)
    )
    rate_limit_transfers_per_minute: int = field(
        default_factory=lambda: _getenv_int("RATE_LIMIT_TRANSFERS_PER_MINUTE", 5)
    )

    sms_outbox_path: str = field(
        default_factory=lambda: os.environ.get("SMS_OUTBOX_PATH", "var/sms_outbox.log")
    )

    def agent_credentials(self) -> dict[str, AgentCredentials]:
        """Seeded agent client registry. Only `assistant-v1` exists, and it
        deliberately never has `transfers:confirm`."""
        return {
            os.environ.get("AGENT_ASSISTANT_V1_CLIENT_ID", "assistant-v1"): AgentCredentials(
                client_id=os.environ.get("AGENT_ASSISTANT_V1_CLIENT_ID", "assistant-v1"),
                client_secret=os.environ.get(
                    "AGENT_ASSISTANT_V1_CLIENT_SECRET", "assistant-v1-secret"
                ),
                scopes=_getenv_list(
                    "AGENT_ASSISTANT_V1_SCOPES",
                    "accounts:read transactions:read transfers:initiate products:read",
                ),
            )
        }


settings = Settings()
