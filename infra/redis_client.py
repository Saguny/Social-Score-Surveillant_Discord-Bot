import os

import redis.asyncio as redis

_client: redis.Redis | None = None


def get_redis() -> redis.Redis:
    global _client
    if _client is None:
        url = os.getenv("REDIS_URL", "redis://localhost:6379")
        _client = redis.from_url(url, decode_responses=True)
    return _client


async def close_redis():
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
