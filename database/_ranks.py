import time
import asyncio


class RanksMixin:
    async def handle_rank_promotion(self, guild_id: int, user_id: int, new_rank_idx: int, yuan_amount: int) -> int:
        now = int(time.time())
        item_id = f"rank_promotion_{new_rank_idx}"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT rank_entered_at FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                prior = await conn.fetchval(
                    "SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = $3",
                    guild_id, user_id, item_id,
                )
                rank_entered_at = (row["rank_entered_at"] or 0) if row else 0
                eligible = prior == 0 or (now - rank_entered_at) >= 30 * 86400
                if eligible:
                    net, _tax = await self._credit_yuan_taxed(conn, guild_id, user_id, yuan_amount)
                    await conn.execute(
                        "UPDATE users SET yuan = GREATEST(0, yuan + $1), total_yuan_earned = total_yuan_earned + $4 WHERE guild_id = $2 AND user_id = $3",
                        net, guild_id, user_id, yuan_amount,
                    )
                    await conn.execute(
                        "INSERT INTO transactions (guild_id, user_id, item_id, cost, timestamp) VALUES ($1, $2, $3, $4, $5)",
                        guild_id, user_id, item_id, yuan_amount, now,
                    )
                await conn.execute(
                    "UPDATE users SET rank_entered_at = $1 WHERE guild_id = $2 AND user_id = $3",
                    now, guild_id, user_id,
                )
        return yuan_amount if eligible else 0

    async def set_rank_entered_at(self, guild_id: int, user_id: int):
        await self._pool.execute(
            "UPDATE users SET rank_entered_at = $1 WHERE guild_id = $2 AND user_id = $3",
            int(time.time()), guild_id, user_id,
        )

    async def update_lottery_stats(self, guild_id: int, user_id: int, won: bool, net: int):
        await self._pool.execute(
            """
            UPDATE users SET
                lottery_played = lottery_played + 1,
                lottery_won    = lottery_won    + $1,
                lottery_lost   = lottery_lost   + $2,
                lottery_net    = lottery_net    + $3
            WHERE guild_id = $4 AND user_id = $5
            """,
            int(won), int(not won), net, guild_id, user_id,
        )

    async def log_rank_departure(self, guild_id: int, user_id: int, rank_name: str):
        now = int(time.time())
        await self._pool.execute(
            """
            WITH src AS (
                SELECT GREATEST(0, ($1 - rank_entered_at) / 86400)::BIGINT AS days
                FROM users
                WHERE guild_id = $2 AND user_id = $3
                  AND rank_entered_at IS NOT NULL AND rank_entered_at > 0
            )
            INSERT INTO rank_history (guild_id, user_id, rank_name, total_days)
            SELECT $2, $3, $4, days FROM src WHERE days > 0
            ON CONFLICT (guild_id, user_id, rank_name)
            DO UPDATE SET total_days = rank_history.total_days + EXCLUDED.total_days
            """,
            now, guild_id, user_id, rank_name,
        )

    async def get_rank_stats(self, guild_id: int, user_id: int, rank_name: str) -> dict:
        now = int(time.time())
        user_row, hist_row = await asyncio.gather(
            self._pool.fetchrow(
                "SELECT rank_entered_at FROM users WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            ),
            self._pool.fetchrow(
                "SELECT total_days FROM rank_history WHERE guild_id = $1 AND user_id = $2 AND rank_name = $3",
                guild_id, user_id, rank_name,
            ),
        )
        entered = (user_row["rank_entered_at"] or 0) if user_row else 0
        current_days = max(0, (now - entered) // 86400) if entered else 0
        hist_days = int(hist_row["total_days"]) if hist_row else 0
        return {"current_days": current_days, "total_days": hist_days + current_days}

    async def increment_execution_count(self, guild_id: int, user_id: int) -> int:
        row = await self._pool.fetchrow(
            "UPDATE users SET execution_count = execution_count + 1 WHERE guild_id = $1 AND user_id = $2 RETURNING execution_count",
            guild_id, user_id,
        )
        return row["execution_count"] if row else 1

    async def get_execution_channel(self, guild_id):
        row = await self._pool.fetchrow(
            "SELECT execution_channel_id FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["execution_channel_id"] if row else None

    async def get_rank_announcement_channel(self, guild_id):
        row = await self._pool.fetchrow(
            "SELECT rank_announcement_channel_id FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["rank_announcement_channel_id"] if row else None

    async def set_rank_announcement_channel(self, guild_id, channel_id):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET rank_announcement_channel_id = $2 WHERE guild_id = $1",
                guild_id, channel_id,
            )

    async def set_execution_channel(self, guild_id, channel_id):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET execution_channel_id = $2 WHERE guild_id = $1",
                guild_id, channel_id,
            )

    async def get_assign_rank_roles(self, guild_id) -> bool:
        row = await self._pool.fetchrow(
            "SELECT assign_rank_roles FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["assign_rank_roles"] if row else True

    async def set_assign_rank_roles(self, guild_id, enabled: bool):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET assign_rank_roles = $2 WHERE guild_id = $1",
                guild_id, enabled,
            )

    async def get_score_log_channel(self, guild_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT score_log_channel_id FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["score_log_channel_id"] if row else None

    async def set_score_log_channel(self, guild_id: int, channel_id: int | None):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET score_log_channel_id = $2 WHERE guild_id = $1",
                guild_id, channel_id,
            )
