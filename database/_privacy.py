import time


class PrivacyMixin:
    async def is_opted_out(self, user_id: int) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM optouts WHERE user_id = $1",
            user_id,
        )
        return row is not None

    async def opt_out_user(self, user_id: int):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO optouts (user_id, opted_out_at) VALUES ($1, $2) ON CONFLICT (user_id) DO NOTHING",
                    user_id, int(time.time()),
                )
                await conn.execute("DELETE FROM users WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM score_history WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM active_effects WHERE user_id = $1", user_id)
                await conn.execute(
                    "DELETE FROM transactions WHERE user_id = $1 OR target_user_id = $1", user_id,
                )
                await conn.execute(
                    "DELETE FROM endorsements WHERE giver_id = $1 OR target_id = $1", user_id,
                )
                await conn.execute("DELETE FROM fundraisers WHERE creator_id = $1", user_id)
                await conn.execute("DELETE FROM fundraiser_donations WHERE donor_id = $1", user_id)
                await conn.execute("DELETE FROM fundraiser_votes WHERE voter_id = $1", user_id)
                await conn.execute("DELETE FROM poster_reactions WHERE user_id = $1", user_id)
                await conn.execute("UPDATE propaganda_events SET mod_id = NULL WHERE mod_id = $1", user_id)
                await conn.execute("DELETE FROM propaganda_submissions WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM propaganda_event_bans WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM guild_decrees WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM eternal_chairmen WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM portfolio_history WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM daily_yuan_snapshots WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM rank_history WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM portfolios WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM turbo_positions WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM vote_reminders WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM topgg_votes WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM achievements WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM cosmetic_badges WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM badge_preferences WHERE user_id = $1", user_id)
                await conn.execute("DELETE FROM user_counters WHERE user_id = $1", user_id)
                await conn.execute(
                    "DELETE FROM achievements_legacy_per_guild WHERE user_id = $1", user_id,
                )
                await conn.execute(
                    "DELETE FROM cosmetic_badges_legacy_per_guild WHERE user_id = $1", user_id,
                )

    async def opt_in_user(self, user_id: int):
        await self._pool.execute("DELETE FROM optouts WHERE user_id = $1", user_id)

    async def get_all_optouts(self) -> set[int]:
        rows = await self._pool.fetch("SELECT user_id FROM optouts")
        return {r["user_id"] for r in rows}
