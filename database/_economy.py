import time
import json
import asyncpg


class EconomyMixin:
    async def increment_reported(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET times_reported = times_reported + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def increment_filed_reports(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET times_filed_reports = times_filed_reports + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def count_distinct_denounce_targets(self, guild_id, user_id) -> int:
        return await self._pool.fetchval(
            "SELECT COUNT(DISTINCT target_user_id) FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = 'denounce'",
            guild_id, user_id,
        )

    async def count_distinct_denouncers(self, guild_id, target_user_id) -> int:
        return await self._pool.fetchval(
            "SELECT COUNT(DISTINCT user_id) FROM transactions WHERE guild_id = $1 AND target_user_id = $2 AND item_id = 'denounce'",
            guild_id, target_user_id,
        )

    async def get_rehabilitation_count(self, guild_id, user_id):
        return await self._pool.fetchval(
            "SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = 'rehabilitate'",
            guild_id, user_id,
        )

    async def log_transaction(self, guild_id, user_id, item_id, cost, target_user_id=None):
        await self._pool.execute(
            "INSERT INTO transactions (guild_id, user_id, item_id, cost, target_user_id, timestamp) VALUES ($1, $2, $3, $4, $5, $6)",
            guild_id, user_id, item_id, cost, target_user_id, int(time.time()),
        )

    async def get_last_action_time(self, guild_id: int, user_id: int, item_id: str, target_user_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT timestamp FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = $3 AND target_user_id = $4 ORDER BY timestamp DESC LIMIT 1",
            guild_id, user_id, item_id, target_user_id,
        )
        return row["timestamp"] if row else None

    async def get_last_self_action_time(self, guild_id: int, user_id: int, item_id: str) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT timestamp FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = $3 AND target_user_id IS NULL ORDER BY timestamp DESC LIMIT 1",
            guild_id, user_id, item_id,
        )
        return row["timestamp"] if row else None

    async def get_last_attacker(self, guild_id: int, user_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT user_id FROM transactions WHERE guild_id = $1 AND target_user_id = $2 AND item_id IN ('report', 'denounce') ORDER BY timestamp DESC LIMIT 1",
            guild_id, user_id,
        )
        return row["user_id"] if row else None

    async def get_random_active_user(self, guild_id: int, exclude_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT user_id FROM users WHERE guild_id = $1 AND user_id != $2 ORDER BY RANDOM() LIMIT 1",
            guild_id, exclude_id,
        )
        return row["user_id"] if row else None

    async def add_fabricated_history(self, guild_id: int, user_id: int, reason: str):
        await self._pool.execute(
            "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, 0, $3, $4)",
            guild_id, user_id, f"[UNVERIFIED REPORT] {reason[:80]}", int(time.time()),
        )

    async def add_cosmetic_badge(self, user_id: int, badge: str):
        await self._pool.execute(
            "INSERT INTO cosmetic_badges (user_id, badge, purchased_at) VALUES ($1, $2, $3) ON CONFLICT DO NOTHING",
            user_id, badge, int(time.time()),
        )

    async def get_cosmetic_badges(self, user_id: int) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT badge FROM cosmetic_badges WHERE user_id = $1 AND (expires_at IS NULL OR expires_at > $2)",
            user_id, int(time.time()),
        )
        return [row["badge"] for row in rows]

    async def add_temporary_cosmetic_badge(self, user_id: int, badge: str, expires_at: int):
        await self._pool.execute(
            """
            INSERT INTO cosmetic_badges (user_id, badge, purchased_at, expires_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, badge) DO UPDATE SET expires_at = $4
            """,
            user_id, badge, int(time.time()), expires_at,
        )

    async def clean_expired_cosmetic_badges(self):
        await self._pool.execute(
            "DELETE FROM cosmetic_badges WHERE expires_at IS NOT NULL AND expires_at <= $1",
            int(time.time()),
        )

    async def set_badge_preference(self, user_id: int, badge_id: str):
        await self._pool.execute(
            "INSERT INTO badge_preferences (user_id, badge_id) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET badge_id = $2",
            user_id, badge_id,
        )

    async def get_badge_preference(self, user_id: int) -> str | None:
        row = await self._pool.fetchrow(
            "SELECT badge_id FROM badge_preferences WHERE user_id = $1",
            user_id,
        )
        return row["badge_id"] if row else None

    async def clear_badge_preference(self, user_id: int):
        await self._pool.execute(
            "DELETE FROM badge_preferences WHERE user_id = $1",
            user_id,
        )

    async def add_eternal_chairman(self, user_id: int):
        await self._pool.execute(
            "INSERT INTO eternal_chairmen (user_id, purchased_at) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, int(time.time()),
        )

    async def get_all_eternal_chairmen(self) -> set[int]:
        rows = await self._pool.fetch("SELECT user_id FROM eternal_chairmen")
        return {row["user_id"] for row in rows}
