"""Persistent dedupe store. Primary: Redis. Fallback: in-memory (dev/tests)."""

from __future__ import annotations

import time
from typing import Protocol

import redis.asyncio as redis_async

from app.logging_config import get_logger

logger = get_logger("dedupe")


class DedupeStore(Protocol):
    async def acquire(self, key: str, ttl_seconds: int) -> bool: ...
    async def aclose(self) -> None: ...


class RedisDedupeStore:
    """SET key NX EX ttl — atomic 'first-writer-wins' lock."""

    def __init__(self, url: str):
        self._client: redis_async.Redis = redis_async.from_url(
            url, decode_responses=True
        )

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        full_key = f"bolna:alerted:{key}"
        # NX: only set if not exists. EX: expiry.
        result = await self._client.set(full_key, "1", nx=True, ex=ttl_seconds)
        return bool(result)

    async def ping(self) -> bool:
        try:
            return bool(await self._client.ping())
        except Exception as e:
            logger.warning("redis_ping_failed", error=str(e))
            return False

    async def aclose(self) -> None:
        await self._client.aclose()


class InMemoryDedupeStore:
    """For tests and local dev when Redis is unavailable."""

    def __init__(self) -> None:
        self._items: dict[str, float] = {}

    async def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = time.time()
        # Clean expired
        self._items = {k: v for k, v in self._items.items() if v > now}
        if key in self._items:
            return False
        self._items[key] = now + ttl_seconds
        return True

    async def ping(self) -> bool:
        return True

    async def aclose(self) -> None:
        self._items.clear()
