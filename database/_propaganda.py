import time
import asyncio


class PropagandaMixin:
    async def create_propaganda_event(self, guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at):
        concludes_at = closes_at + 86400
        row = await self._pool.fetchrow(
            """
            INSERT INTO propaganda_events (guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at, concludes_at)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """,
            guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at, concludes_at,
        )
        return row["id"]

    async def get_open_propaganda_event(self, guild_id):
        return await self._pool.fetchrow(
            "SELECT * FROM propaganda_events WHERE guild_id = $1 AND status = 'open' AND closes_at > $2",
            guild_id, int(time.time()),
        )

    async def get_propaganda_events_ready_to_close(self, now):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_events WHERE status = 'open' AND closes_at <= $1", now,
        )

    async def get_propaganda_events_ready_to_conclude(self, now):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_events WHERE status = 'voting' AND concludes_at <= $1", now,
        )

    async def set_propaganda_event_status(self, event_id, status):
        await self._pool.execute(
            "UPDATE propaganda_events SET status = $1 WHERE id = $2", status, event_id,
        )

    async def add_propaganda_submission(self, event_id, guild_id, user_id, content):
        now = int(time.time())
        row = await self._pool.fetchrow(
            "INSERT INTO propaganda_submissions (event_id, guild_id, user_id, content, timestamp) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            event_id, guild_id, user_id, content, now,
        )
        return row["id"]

    async def get_propaganda_submission_by_user(self, event_id, user_id):
        return await self._pool.fetchrow(
            "SELECT * FROM propaganda_submissions WHERE event_id = $1 AND user_id = $2",
            event_id, user_id,
        )

    async def is_propaganda_banned(self, event_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT 1 FROM propaganda_event_bans WHERE event_id = $1 AND user_id = $2",
            event_id, user_id,
        )
        return row is not None

    async def ban_from_propaganda_event(self, event_id, guild_id, user_id, matched_content):
        await self._pool.execute(
            "INSERT INTO propaganda_event_bans (event_id, guild_id, user_id, matched_content) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            event_id, guild_id, user_id, matched_content,
        )

    async def get_propaganda_submissions(self, event_id):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_submissions WHERE event_id = $1 ORDER BY timestamp ASC",
            event_id,
        )

    async def set_submission_reveal_message(self, submission_id, message_id):
        await self._pool.execute(
            "UPDATE propaganda_submissions SET reveal_message_id = $1 WHERE id = $2",
            message_id, submission_id,
        )

    async def add_guild_decree(self, guild_id, user_id, content, vote_count):
        now = int(time.time())
        await asyncio.gather(
            self._pool.execute(
                "INSERT INTO guild_decrees (guild_id, user_id, content, won_at, vote_count) VALUES ($1, $2, $3, $4, $5)",
                guild_id, user_id, content, now, vote_count,
            ),
            self._pool.execute(
                "UPDATE users SET propaganda_wins = propaganda_wins + 1 WHERE guild_id = $1 AND user_id = $2",
                guild_id, user_id,
            ),
        )

    async def get_guild_decrees(self, guild_id, limit=10):
        return await self._pool.fetch(
            "SELECT * FROM guild_decrees WHERE guild_id = $1 ORDER BY won_at DESC LIMIT $2",
            guild_id, limit,
        )
