import time


class PostersMixin:
    async def get_poster_guilds(self):
        return await self._pool.fetch("SELECT guild_id, channel_id, last_slug FROM poster_config")

    async def enable_posters(self, guild_id, channel_id):
        await self._pool.execute(
            "INSERT INTO poster_config (guild_id, channel_id, last_slug) VALUES ($1, $2, '') "
            "ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id",
            guild_id, channel_id,
        )

    async def disable_posters(self, guild_id):
        await self._pool.execute("DELETE FROM poster_config WHERE guild_id = $1", guild_id)

    async def set_poster_last(self, guild_id, slug):
        await self._pool.execute(
            "UPDATE poster_config SET last_slug = $1 WHERE guild_id = $2", slug, guild_id
        )

    async def log_poster_message(self, guild_id, channel_id, message_id):
        await self._pool.execute(
            "INSERT INTO poster_messages (guild_id, message_id, channel_id) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING",
            guild_id, message_id, channel_id,
        )

    async def get_poster_message(self, guild_id, message_id):
        return await self._pool.fetchrow(
            "SELECT * FROM poster_messages WHERE guild_id = $1 AND message_id = $2",
            guild_id, message_id,
        )

    async def record_poster_reaction(self, message_id: int, user_id: int) -> bool:
        result = await self._pool.execute(
            "INSERT INTO poster_reactions (message_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            message_id, user_id,
        )
        return result == "INSERT 0 1"
