import time
import json
import random


class EffectsMixin:
    async def add_effect(self, guild_id, user_id, effect_type, expires_at, metadata=None):
        await self._pool.execute(
            "INSERT INTO active_effects (guild_id, user_id, effect_type, metadata, expires_at) VALUES ($1, $2, $3, $4, $5)",
            guild_id, user_id, effect_type, json.dumps(metadata or {}), expires_at,
        )
        self.invalidate_effect_cache(guild_id, user_id, effect_type)

    async def get_effect(self, guild_id, user_id, effect_type):
        now = time.time()
        cache_key = (guild_id, user_id, effect_type)
        if cache_key in self._effect_cache:
            cached_at, row = self._effect_cache[cache_key]
            if now - cached_at < 30 and (row is None or row["expires_at"] > int(now)):
                return row
        row = await self._pool.fetchrow(
            "SELECT * FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4",
            guild_id, user_id, effect_type, int(now),
        )
        self._effect_cache[cache_key] = (now, row)
        return row

    async def consume_effect(self, guild_id: int, user_id: int, effect_type: str) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM active_effects WHERE id = (SELECT id FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4 LIMIT 1) RETURNING id",
            guild_id, user_id, effect_type, int(time.time()),
        )
        if row:
            self._effect_cache.pop((guild_id, user_id, effect_type), None)
        return row is not None

    def invalidate_effect_cache(self, guild_id, user_id, effect_type):
        self._effect_cache.pop((guild_id, user_id, effect_type), None)

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
