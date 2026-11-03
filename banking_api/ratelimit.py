"""Redis sliding-window rate limiter, keyed on `agent_id:customer_id`
(section 5): 30 reads/minute, 5 `POST /transfers`/minute. A loop or a
misbehaving agent can only generate so many calls per minute per customer,
regardless of how fast it tries."""

from __future__ import annotations

import time
import uuid

import redis as redis_lib
from fastapi import Depends

from banking_api.auth import EffectivePrincipal, get_effective_principal
from banking_api.config import settings
from banking_api.errors import AppError
from banking_api.redis_client import get_redis

WINDOW_SECONDS = 60


def _check(redis_client: redis_lib.Redis, key: str, limit: int) -> int | None:
    """Returns None if the request is allowed, or seconds-until-retry if not."""
    now = time.time()
    redis_client.zremrangebyscore(key, 0, now - WINDOW_SECONDS)
    count = redis_client.zcard(key)
    if count >= limit:
        oldest = redis_client.zrange(key, 0, 0, withscores=True)
        oldest_score = oldest[0][1] if oldest else now
        return max(1, int(WINDOW_SECONDS - (now - oldest_score)))

    redis_client.zadd(key, {str(uuid.uuid4()): now})
    redis_client.expire(key, WINDOW_SECONDS)
    return None


def rate_limit(category: str, limit: int):
    def checked(
        principal: EffectivePrincipal = Depends(get_effective_principal),
    ) -> EffectivePrincipal:
        key = f"ratelimit:{category}:{principal.agent_id}:{principal.customer_id}"
        retry_after = _check(get_redis(), key, limit)
        if retry_after is not None:
            raise AppError(
                429,
                "rate_limited",
                f"Too many {category} requests. Retry after {retry_after}s.",
                audit_reason=f"rate_limited:{category}",
                headers={"Retry-After": str(retry_after)},
            )
        return principal

    return checked


rate_limit_reads = rate_limit("read", settings.rate_limit_reads_per_minute)
rate_limit_transfers = rate_limit("transfer", settings.rate_limit_transfers_per_minute)
