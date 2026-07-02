import time

from discord.ext import commands, tasks

from infra.redis_client import get_redis
from infra.guild_notify import publish_guild_notify

_POLL_INTERVAL_SECS = 1
_SCAN_PATTERN = "ach:ready:*"


class AchievementsScheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self._poll_ready.start()

    async def cog_unload(self):
        self._poll_ready.cancel()

    @tasks.loop(seconds=_POLL_INTERVAL_SECS)
    async def _poll_ready(self):
        r = get_redis()
        now = int(time.time())
        async for key in r.scan_iter(match=_SCAN_PATTERN):
            ready_at_raw = await r.get(key)
            if ready_at_raw is None:
                continue
            if now < int(ready_at_raw):
                continue
            _, _, guild_id_str, user_id_str = key.split(":")
            await self._flush(int(guild_id_str), int(user_id_str))

    async def _flush(self, guild_id: int, user_id: int):
        r = get_redis()
        key_ids = f"ach:ids:{guild_id}:{user_id}"
        key_channel = f"ach:channel:{guild_id}:{user_id}"
        key_ready = f"ach:ready:{guild_id}:{user_id}"

        ids = await r.lrange(key_ids, 0, -1)
        channel_id_raw = await r.get(key_channel)
        await r.delete(key_ids, key_channel, key_ready)
        if not ids:
            return

        await publish_guild_notify(guild_id, "achievement_announce", {
            "user_id": user_id,
            "ids": ids,
            "channel_id": int(channel_id_raw) if channel_id_raw else None,
        })


async def setup(bot: commands.Bot):
    await bot.add_cog(AchievementsScheduler(bot))
