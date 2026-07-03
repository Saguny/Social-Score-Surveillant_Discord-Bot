import asyncio
import json
import time

from infra.redis_client import get_redis
from .constants import CLAIM_WINDOW


async def get_roll_state(guild_id: int, user_id: int) -> tuple[int, int]:
    """Returns (rolls_used, ttl_seconds)."""
    r = get_redis()
    key = f"gacha:rolls:{guild_id}:{user_id}"
    raw, ttl = await asyncio.gather(r.get(key), r.ttl(key))
    return (int(raw) if raw else 0), max(int(ttl), 0)


async def increment_rolls(guild_id: int, user_id: int) -> int:
    r   = get_redis()
    key = f"gacha:rolls:{guild_id}:{user_id}"
    n   = await r.incr(key)
    if n == 1:
        await r.expire(key, 3600 - (int(time.time()) % 3600))
    return n


async def decrement_rolls(guild_id: int, user_id: int) -> None:
    await get_redis().decr(f"gacha:rolls:{guild_id}:{user_id}")


async def get_owner(guild_id: int, char_id: str, db) -> int | None:
    r   = get_redis()
    key = f"gacha:owner:{guild_id}:{char_id}"
    cached = await r.get(key)
    if cached is not None:
        return int(cached) if cached not in (b"0", "0") else None
    owner_id = await db.get_character_owner(guild_id, char_id)
    await r.set(key, str(owner_id) if owner_id else "0", ex=300)
    return owner_id


async def set_owner(guild_id: int, char_id: str, owner_id: int | None) -> None:
    r = get_redis()
    await r.set(f"gacha:owner:{guild_id}:{char_id}", str(owner_id) if owner_id else "0", ex=300)


async def get_claim_state(guild_id: int, user_id: int) -> tuple[int, int]:
    """Returns (claims_used, ttl_seconds)."""
    r = get_redis()
    key = f"gacha:claims:{guild_id}:{user_id}"
    raw, ttl = await asyncio.gather(r.get(key), r.ttl(key))
    return (int(raw) if raw else 0), max(int(ttl), 0)


async def increment_claims(guild_id: int, user_id: int) -> int:
    r   = get_redis()
    key = f"gacha:claims:{guild_id}:{user_id}"
    n   = await r.incr(key)
    if n == 1:
        await r.expire(key, 3600 - (int(time.time()) % 3600))
    return n


async def decrement_claims(guild_id: int, user_id: int) -> None:
    await get_redis().decr(f"gacha:claims:{guild_id}:{user_id}")


async def store_pending(message_id: int, data: dict) -> None:
    await get_redis().set(f"gacha:pending:{message_id}", json.dumps(data), ex=CLAIM_WINDOW)


async def pop_pending(message_id: int) -> tuple[dict | None, int]:
    """Returns (data_dict, remaining_ttl). data is None if key doesn't exist."""
    r   = get_redis()
    key = f"gacha:pending:{message_id}"
    ttl = await r.ttl(key)
    raw = await r.getdel(key)
    if raw is None:
        return None, 0
    try:
        return json.loads(raw), max(int(ttl), 0)
    except (TypeError, ValueError):
        return None, 0


async def set_rate_limit_warned(guild_id: int, user_id: int) -> bool:
    """Atomically set a 15s dedupe flag. Returns True if this is the first warning."""
    return bool(await get_redis().set(f"gacha:rl_warn:{guild_id}:{user_id}", "1", nx=True, ex=15))
