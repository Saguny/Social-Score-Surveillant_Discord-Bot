import time


class AchievementsMixin:
    async def has_achievement(self, user_id: int, achievement_id: str) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM achievements WHERE user_id = $1 AND achievement_id = $2",
            user_id, achievement_id,
        )
        return row is not None

    async def unlock_achievement(self, user_id: int, achievement_id: str, origin_guild_id: int | None = None) -> bool:
        row = await self._pool.fetchrow(
            """
            INSERT INTO achievements (user_id, achievement_id, unlocked_at, origin_guild_id)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, achievement_id) DO NOTHING
            RETURNING 1
            """,
            user_id, achievement_id, int(time.time()), origin_guild_id,
        )
        return row is not None

    async def get_unlocked_achievements(self, user_id: int) -> list[dict]:
        rows = await self._pool.fetch(
            "SELECT achievement_id, unlocked_at FROM achievements WHERE user_id = $1",
            user_id,
        )
        return [{"achievement_id": r["achievement_id"], "unlocked_at": r["unlocked_at"]} for r in rows]

    async def get_achievement_counts(self) -> dict[str, int]:
        rows = await self._pool.fetch(
            "SELECT achievement_id, COUNT(*) AS n FROM achievements GROUP BY achievement_id",
        )
        return {r["achievement_id"]: int(r["n"]) for r in rows}

    async def get_total_citizen_count(self) -> int:
        row = await self._pool.fetchrow("SELECT COUNT(DISTINCT user_id) AS n FROM users")
        return int(row["n"]) if row else 0

    async def get_achievement_server_rank(self, guild_id: int, user_id: int) -> tuple[int, int]:
        row = await self._pool.fetchrow(
            """
            WITH ranked AS (
                SELECT u.user_id,
                       RANK() OVER (ORDER BY COUNT(a.achievement_id) DESC) AS rnk
                FROM users u
                LEFT JOIN achievements a ON a.user_id = u.user_id
                WHERE u.guild_id = $1
                GROUP BY u.user_id
            )
            SELECT rnk, (SELECT COUNT(*) FROM users WHERE guild_id = $1) AS total
            FROM ranked
            WHERE user_id = $2
            """,
            guild_id, user_id,
        )
        if not row:
            return 0, 0
        return int(row["rnk"]), int(row["total"])

    async def get_achievements_channel(self, guild_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT achievements_channel_id, achievements_loud_enabled FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        if not row or not row["achievements_loud_enabled"]:
            return None
        return row["achievements_channel_id"]

    async def get_achievements_loud_enabled(self, guild_id: int) -> bool:
        row = await self._pool.fetchrow(
            "SELECT achievements_loud_enabled FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["achievements_loud_enabled"] if row else True

    async def set_achievements_channel(self, guild_id: int, channel_id: int | None):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET achievements_channel_id = $2 WHERE guild_id = $1",
                guild_id, channel_id,
            )

    async def set_achievements_loud_enabled(self, guild_id: int, enabled: bool):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET achievements_loud_enabled = $2 WHERE guild_id = $1",
                guild_id, enabled,
            )
