import time
import asyncio


class SocialMixin:
    async def get_endorsement(self, guild_id, giver_id, target_id):
        return await self._pool.fetchrow(
            "SELECT * FROM endorsements WHERE guild_id = $1 AND giver_id = $2 AND target_id = $3",
            guild_id, giver_id, target_id,
        )

    async def set_endorsement(self, guild_id, giver_id, target_id, etype):
        await self._pool.execute(
            "INSERT INTO endorsements (guild_id, giver_id, target_id, type, timestamp) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, giver_id, target_id) DO UPDATE SET type = EXCLUDED.type, timestamp = EXCLUDED.timestamp",
            guild_id, giver_id, target_id, etype, int(time.time()),
        )

    async def update_social_counts(self, guild_id, target_id, uid, etype):
        recv_col  = "times_endorsed"     if etype == "endorse" else "times_rebuked"
        given_col = "endorsements_given" if etype == "endorse" else "rebukes_given"
        await asyncio.gather(
            self._pool.execute(
                f"UPDATE users SET {recv_col} = {recv_col} + 1 WHERE guild_id = $1 AND user_id = $2",
                guild_id, target_id,
            ),
            self._pool.execute(
                f"UPDATE users SET {given_col} = {given_col} + 1 WHERE guild_id = $1 AND user_id = $2",
                guild_id, uid,
            ),
        )
