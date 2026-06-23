import time
import json
import random

from infra.redis_cache import cache_get, cache_set, cache_delete

_EFFECT_CACHE_TTL = 30


def _effect_cache_key(guild_id, user_id, effect_type):
    return f"effect:{guild_id}:{user_id}:{effect_type}"


class EffectsMixin:
    async def add_effect(self, guild_id, user_id, effect_type, expires_at, metadata=None):
        await self._pool.execute(
            "INSERT INTO active_effects (guild_id, user_id, effect_type, metadata, expires_at) VALUES ($1, $2, $3, $4, $5)",
            guild_id, user_id, effect_type, json.dumps(metadata or {}), expires_at,
        )
        await self.invalidate_effect_cache(guild_id, user_id, effect_type)

    async def get_effect(self, guild_id, user_id, effect_type):
        now = time.time()
        cache_key = _effect_cache_key(guild_id, user_id, effect_type)
        cached = await cache_get(cache_key)
        if cached is not None:
            return None if cached == "null" else json.loads(cached)
        row = await self._pool.fetchrow(
            "SELECT * FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4",
            guild_id, user_id, effect_type, int(now),
        )
        value = "null" if row is None else json.dumps(dict(row))
        await cache_set(cache_key, value, ex=_EFFECT_CACHE_TTL)
        return None if row is None else dict(row)

    async def consume_effect(self, guild_id: int, user_id: int, effect_type: str) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM active_effects WHERE id = (SELECT id FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4 LIMIT 1) RETURNING id",
            guild_id, user_id, effect_type, int(time.time()),
        )
        if row:
            await self.invalidate_effect_cache(guild_id, user_id, effect_type)
        return row is not None

    async def invalidate_effect_cache(self, guild_id, user_id, effect_type):
        await cache_delete(_effect_cache_key(guild_id, user_id, effect_type))

    async def apply_defense_chain(self, guild_id: int, target_id: int, base_delta: float) -> tuple[float, str | None]:
        if base_delta >= 0:
            return base_delta, None
        if await self.get_effect(guild_id, target_id, "criticism"):
            base_delta *= 2
        if await self.consume_effect(guild_id, target_id, "exception"):
            return 0.0, "exception"
        if await self.consume_effect(guild_id, target_id, "immunity"):
            if random.random() < 0.5:
                return 0.0, "immunity"
        reduction = 1.0
        if await self.consume_effect(guild_id, target_id, "appeal"):
            reduction *= 0.5
        if await self.consume_effect(guild_id, target_id, "protection"):
            reduction *= 0.5
        if await self.get_effect(guild_id, target_id, "legal_rep"):
            reduction *= 0.5
        return round(base_delta * reduction, 2), None

    async def consume_surveillance_for_target(self, guild_id: int, user_id: int, target_id: int) -> bool:
        rows = await self._pool.fetch(
            "SELECT id, metadata FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = 'surveillance' AND expires_at > $3",
            guild_id, user_id, int(time.time()),
        )
        effect_id = next(
            (row["id"] for row in rows if json.loads(row["metadata"]).get("target_id") == target_id),
            None,
        )
        if effect_id is None:
            return False
        await self._pool.execute("DELETE FROM active_effects WHERE id = $1", effect_id)
        return True

    async def consume_investigation_bounty(self, guild_id: int, target_id: int) -> dict | None:
        rows = await self._pool.fetch(
            "SELECT id, metadata FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = 'investigation' AND expires_at > $3",
            guild_id, target_id, int(time.time()),
        )
        if not rows:
            return None
        row = rows[0]
        await self._pool.execute("DELETE FROM active_effects WHERE id = $1", row["id"])
        return json.loads(row["metadata"])
