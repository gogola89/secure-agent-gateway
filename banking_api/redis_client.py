from __future__ import annotations

from functools import lru_cache

import redis

from banking_api.config import settings


@lru_cache
def get_redis() -> redis.Redis:
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)
