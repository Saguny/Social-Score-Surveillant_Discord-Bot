from infra.redis_client import get_redis


async def cache_get(key: str) -> str | None:
    r = get_redis()
    return await r.get(key)


async def cache_set(key: str, value, ex: int | None = None) -> None:
    r = get_redis()
    await r.set(key, value, ex=ex)


async def cache_set_nx(key: str, value, ex: int | None = None) -> bool:
    r = get_redis()
    ok = await r.set(key, value, nx=True, ex=ex)
    return bool(ok)


async def cache_delete(key: str) -> None:
    r = get_redis()
    await r.delete(key)


async def cache_incr(key: str, ex: int | None = None) -> int:
    r = get_redis()
    val = await r.incr(key)
    if ex is not None:
        await r.expire(key, ex)
    return val


async def cache_mget(keys: list[str]) -> list[str | None]:
    if not keys:
        return []
    r = get_redis()
    return await r.mget(*keys)
