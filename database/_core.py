import time
import asyncio
import math

from config.rules import WEALTH_TAX_THRESHOLD, WEALTH_TAX_RATE, GLOBAL_YUAN_SNAPSHOT_RETENTION_DAYS


class CoreMixin:
    async def _ensure_guild(self, conn, guild_id):
        await conn.execute(
            "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING",
            guild_id,
        )

    async def _credit_yuan_taxed(self, conn, guild_id, user_id, gross_amount):
        if gross_amount <= 0:
            return gross_amount, 0
        row = await conn.fetchrow(
            "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2 FOR UPDATE",
            guild_id, user_id,
        )
        old_yuan = row["yuan"] if row else 0
        tax = math.floor(gross_amount * WEALTH_TAX_RATE) if old_yuan >= WEALTH_TAX_THRESHOLD else 0
        if tax > 0:
            await conn.execute(
                "UPDATE bureau_treasury SET total = total + $1 WHERE id = 1",
                tax,
            )
        return gross_amount - tax, tax

    async def get_treasury_total(self) -> int:
        row = await self._pool.fetchrow("SELECT total FROM bureau_treasury WHERE id = 1")
        return row["total"] if row else 0

    async def register_user(self, guild_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.execute(
                    "INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score) VALUES ($1, $2, 750.0, 750.0, 750.0) ON CONFLICT (guild_id, user_id) DO NOTHING",
                    guild_id, user_id,
                )

    async def register_guild_members(self, guild_id, user_ids, chunk_size: int = 500):
        if not user_ids:
            return
        await self._pool.execute(
            "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT DO NOTHING",
            guild_id,
        )
        sql = "INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score) VALUES ($1, $2, 750.0, 750.0, 750.0) ON CONFLICT (guild_id, user_id) DO NOTHING"
        ids = list(user_ids)
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            async with self._pool.acquire() as conn:
                await conn.executemany(sql, [(guild_id, uid) for uid in chunk])
            await asyncio.sleep(0)

    async def log_guild_join(self, guild_id):
        await self._pool.execute(
            "INSERT INTO guild_joins (guild_id, joined_at) VALUES ($1, $2)",
            guild_id, int(time.time()),
        )

    async def log_guild_leave(self, guild_id, member_count, tenure_seconds, citizens, score_events, category):
        await self._pool.execute(
            """
            INSERT INTO guild_leaves (guild_id, left_at, member_count, tenure_seconds, citizens, score_events, category)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            guild_id, int(time.time()), member_count, tenure_seconds, citizens, score_events, category,
        )

    async def get_guild_departure_context(self, guild_id) -> dict:
        citizens, score_events, joined_row = await asyncio.gather(
            self._pool.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND has_chatted = 1", guild_id
            ),
            self._pool.fetchval(
                "SELECT COUNT(*) FROM score_history WHERE guild_id = $1", guild_id
            ),
            self._pool.fetchrow(
                "SELECT joined_at FROM guild_joins WHERE guild_id = $1 ORDER BY joined_at DESC LIMIT 1", guild_id
            ),
        )
        return {
            "citizens": citizens or 0,
            "score_events": score_events or 0,
            "joined_at": joined_row["joined_at"] if joined_row else None,
        }

    async def tick_user(self, guild_id, user_id, yuan):
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                net, _tax = await self._credit_yuan_taxed(conn, guild_id, user_id, yuan)
                return await conn.fetchrow(
                    """
                    INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score,
                                       message_count, yuan, total_yuan_earned, has_chatted, last_active)
                    VALUES ($1, $2, 750.0, 750.0, 750.0, 1, $3, $5, 1, $4)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        message_count     = users.message_count + 1,
                        yuan              = users.yuan + $3,
                        total_yuan_earned = users.total_yuan_earned + $5,
                        has_chatted       = 1,
                        last_active       = $4
                    RETURNING *
                    """,
                    guild_id, user_id, net, now, yuan,
                )

    async def get_user(self, guild_id, user_id):
        await self.register_user(guild_id, user_id)
        return await self._pool.fetchrow(
            "SELECT * FROM users WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def get_user_guild_ids(self, user_id):
        rows = await self._pool.fetch(
            "SELECT guild_id FROM users WHERE user_id = $1",
            user_id,
        )
        return [r["guild_id"] for r in rows]

    async def get_chatted_user_ids(self, guild_id: int) -> list[int]:
        rows = await self._pool.fetch(
            "SELECT user_id FROM users WHERE guild_id = $1 AND has_chatted = 1",
            guild_id,
        )
        return [r["user_id"] for r in rows]

    async def get_user_all_guilds(self, user_id: int) -> list[dict]:
        from config.ranks import get_rank
        rows = await self._pool.fetch(
            """
            SELECT u.guild_id, u.score, u.yuan, g.guild_name
            FROM users u
            LEFT JOIN guild_config g ON g.guild_id = u.guild_id
            WHERE u.user_id = $1
            ORDER BY u.score DESC
            """,
            user_id,
        )
        return [
            {**dict(r), "rank": get_rank(r["score"])["name"]}
            for r in rows
        ]

    async def confiscate_yuan(self, guild_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not row or row["yuan"] <= 0:
                    return 0
                total = row["yuan"]
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND user_id != $2",
                    guild_id, user_id,
                )
                if count and count > 0:
                    share = total // count
                    if share > 0:
                        await conn.execute(
                            "UPDATE users SET yuan = yuan + $3 WHERE guild_id = $1 AND user_id != $2",
                            guild_id, user_id, share,
                        )
                await conn.execute(
                    "UPDATE users SET yuan = 0 WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                return total

    async def get_condemned_users(self, guild_id):
        return await self._pool.fetch(
            "SELECT user_id, yuan FROM users WHERE guild_id = $1 AND score <= 610",
            guild_id,
        )

    async def adjust_yuan(self, guild_id, user_id, amount):
        if amount > 0:
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    net, _tax = await self._credit_yuan_taxed(conn, guild_id, user_id, amount)
                    await conn.execute(
                        "UPDATE users SET yuan = GREATEST(0, yuan + $3), total_yuan_earned = total_yuan_earned + $4 WHERE guild_id = $1 AND user_id = $2",
                        guild_id, user_id, net, amount,
                    )
        else:
            await self._pool.execute(
                "UPDATE users SET yuan = GREATEST(0, yuan + $3) WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id, amount,
            )

    async def set_yuan(self, guild_id: int, user_id: int, amount: int):
        await self._pool.execute(
            "UPDATE users SET yuan = GREATEST(0, $3) WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id, amount,
        )

    async def set_score(self, guild_id: int, user_id: int, score: float):
        await self._pool.execute(
            """
            UPDATE users SET
                score         = GREATEST(600.0, LEAST(1300.0, $3)),
                highest_score = GREATEST(highest_score, GREATEST(600.0, LEAST(1300.0, $3))),
                lowest_score  = LEAST(lowest_score,     GREATEST(600.0, LEAST(1300.0, $3)))
            WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id, user_id, score,
        )

    async def add_yuan(self, guild_id, user_id, amount):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                net, _tax = await self._credit_yuan_taxed(conn, guild_id, user_id, amount)
                await conn.execute(
                    "UPDATE users SET yuan = yuan + $1, total_yuan_earned = total_yuan_earned + $2 WHERE guild_id = $3 AND user_id = $4",
                    net, amount, guild_id, user_id,
                )

    async def spend_yuan(self, guild_id, user_id, amount):
        row = await self._pool.fetchrow(
            "UPDATE users SET yuan = yuan - $3, total_yuan_spent = total_yuan_spent + $3 WHERE guild_id = $1 AND user_id = $2 AND yuan >= $3 RETURNING yuan",
            guild_id, user_id, amount,
        )
        return row is not None

    async def update_score(self, guild_id, user_id, delta, reason):
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    WITH old AS (
                        SELECT score FROM users WHERE guild_id = $1 AND user_id = $2
                    ), ensure AS (
                        INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score)
                        VALUES ($1, $2, 750.0, 750.0, 750.0)
                        ON CONFLICT DO NOTHING
                    ), updated AS (
                        UPDATE users SET
                            score         = GREATEST(600.0, LEAST(1300.0, score + $3)),
                            highest_score = GREATEST(highest_score, GREATEST(600.0, LEAST(1300.0, score + $3))),
                            lowest_score  = LEAST(lowest_score,     GREATEST(600.0, LEAST(1300.0, score + $3)))
                        WHERE guild_id = $1 AND user_id = $2
                        RETURNING score
                    ), history AS (
                        INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp)
                        SELECT $1, $2, ROUND($3::numeric, 2), $4, $5
                        FROM updated
                    )
                    SELECT
                        COALESCE((SELECT score FROM old), 750.0) AS old_score,
                        (SELECT score FROM updated)              AS new_score
                    """,
                    guild_id, user_id, delta, reason, now,
                )
        return row["old_score"], row["new_score"]

    async def mark_chatted(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET has_chatted = 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def increment_message_count(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def clean_expired_effects(self):
        now = time.time()
        if now - self._last_clean_effects < 60:
            return
        self._last_clean_effects = now
        await self._pool.execute("DELETE FROM active_effects WHERE expires_at <= $1", int(now))

    async def increment_report_counter(self, guild_id):
        row = await self._pool.fetchrow(
            "UPDATE guild_config SET report_counter = report_counter + 1 WHERE guild_id = $1 RETURNING report_counter",
            guild_id,
        )
        return row["report_counter"] if row else 0

    async def increment_items_bought(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET items_bought = items_bought + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def get_confirm_threshold(self, guild_id):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            row = await conn.fetchrow(
                "SELECT confirm_threshold FROM guild_config WHERE guild_id = $1", guild_id
            )
        return row["confirm_threshold"] if row else 3

    async def set_confirm_threshold(self, guild_id, n):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.execute(
                    "UPDATE guild_config SET confirm_threshold = $1 WHERE guild_id = $2", n, guild_id
                )

    async def reset_guild_db(self, guild_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for table in ["users", "score_history", "active_effects", "transactions", "endorsements", "fundraiser_donations", "fundraisers"]:
                    await conn.execute(f"DELETE FROM {table} WHERE guild_id = $1", guild_id)
                await conn.execute("DELETE FROM fundraiser_votes WHERE fundraiser_id NOT IN (SELECT id FROM fundraisers)")
                await conn.execute("UPDATE guild_config SET report_counter = 0 WHERE guild_id = $1", guild_id)

    async def do_checkin(self, user_id, guild_ids):
        now = int(time.time())
        today = now // 86400

        last_day = await self.get_counter(user_id, "checkin:last_day")
        if last_day == today:
            return {"already_checked_in": True}

        prev_streak = await self.get_counter(user_id, "checkin:streak")
        new_streak = prev_streak + 1 if last_day == today - 1 else 1
        yuan_reward = min(250 + (new_streak - 1) * 100, 2000)
        score_delta = round(min(2.0 + (new_streak - 1) * 0.1, 5.0), 2)

        async with self._pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO user_counters (user_id, counter_key, value) VALUES ($1, $2, $3) "
                "ON CONFLICT (user_id, counter_key) DO UPDATE SET value = EXCLUDED.value",
                [(user_id, "checkin:last_day", today), (user_id, "checkin:streak", new_streak)],
            )

        results = await asyncio.gather(*(
            self._apply_checkin_guild(gid, user_id, now, new_streak, yuan_reward, score_delta)
            for gid in guild_ids
        ))
        guild_results = [r for r in results if r]

        return {
            "already_checked_in": False, "streak": new_streak,
            "yuan_reward": yuan_reward, "score_delta": score_delta,
            "guilds_rewarded": len(guild_results), "guild_results": guild_results,
        }

    async def _apply_checkin_guild(self, guild_id, user_id, now, streak, yuan_reward, score_delta):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT score FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not row:
                    return None
                old_score = row["score"]
                new_score = min(1300.0, old_score + score_delta)
                net, _tax = await self._credit_yuan_taxed(conn, guild_id, user_id, yuan_reward)
                await conn.execute(
                    """
                    UPDATE users SET
                        last_checkin           = $1,
                        checkin_streak         = $2,
                        longest_checkin_streak = GREATEST(longest_checkin_streak, $2),
                        yuan                   = yuan + $3,
                        total_yuan_earned      = total_yuan_earned + $7,
                        score                  = $4,
                        highest_score          = GREATEST(highest_score, $4)
                    WHERE guild_id = $5 AND user_id = $6
                    """,
                    now, streak, net, new_score, guild_id, user_id, yuan_reward,
                )
                await conn.execute(
                    "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, $3, $4, $5)",
                    guild_id, user_id, score_delta, f"daily check-in (streak: {streak})", now,
                )
        return {"guild_id": guild_id, "old_score": old_score, "new_score": new_score}

    async def apply_score_decay(self):
        cutoff = int(time.time()) - (7 * 86400)
        await self._pool.execute(
            """
            UPDATE users SET
                score        = GREATEST(600.0, score - 0.1),
                lowest_score = LEAST(lowest_score, GREATEST(600.0, score - 0.1))
            WHERE has_chatted = 1
            AND last_active > 0
            AND last_active < $1
            AND score > 600.0
            """,
            cutoff,
        )
        await self._pool.execute("UPDATE users SET prev_day_yuan = yuan")
        await self.prune_portfolio_history()
        today = int(time.time()) // 86400 * 86400
        await self._pool.execute(
            """
            INSERT INTO daily_yuan_snapshots (guild_id, user_id, day, yuan)
            SELECT guild_id, user_id, $1, yuan FROM users
            ON CONFLICT (guild_id, user_id, day) DO UPDATE SET yuan = EXCLUDED.yuan
            """,
            today,
        )
        await self.snapshot_global_yuan_earned()
        await self.prune_global_yuan_earned_snapshots()

    async def snapshot_global_yuan_earned(self):
        today = int(time.time()) // 86400 * 86400
        await self._pool.execute(
            """
            INSERT INTO global_yuan_earned_snapshots (user_id, day, total_yuan_earned)
            SELECT user_id, $1, SUM(total_yuan_earned) FROM users GROUP BY user_id
            ON CONFLICT (user_id, day) DO UPDATE SET total_yuan_earned = EXCLUDED.total_yuan_earned
            """,
            today,
        )

    async def prune_global_yuan_earned_snapshots(self):
        cutoff = int(time.time()) // 86400 * 86400 - (GLOBAL_YUAN_SNAPSHOT_RETENTION_DAYS * 86400)
        await self._pool.execute(
            "DELETE FROM global_yuan_earned_snapshots WHERE day < $1",
            cutoff,
        )
