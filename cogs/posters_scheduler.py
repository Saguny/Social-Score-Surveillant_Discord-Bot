import random
import datetime
import discord
from discord.ext import commands, tasks
from config.poster_data import POSTERS
from cogs.posters import _build_embed, HEART, RAGE


class PostersScheduler(commands.Cog):
    """Background daily poster broadcast loop.

    No app_commands, prefix commands, or reaction listeners live here -- those
    stay on cogs.posters.Posters (gateway workers). This cog queries
    db.get_poster_guilds() fresh on every tick rather than caching active
    guild config in memory, since the loop only runs once a day and a stale
    in-process cache here would drift out of sync with `ccp posters [on|off]`
    toggles applied on a gateway worker process.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self._daily_poster.start()

    async def cog_unload(self):
        self._daily_poster.cancel()

    @tasks.loop(time=datetime.time(hour=12, minute=0, tzinfo=datetime.timezone.utc))
    async def _daily_poster(self):
        for row in await self.db.get_poster_guilds():
            channel = self.bot.get_channel(row["channel_id"])
            if not channel:
                continue
            await self._send_daily(channel, row["guild_id"], row["last_slug"])

    @_daily_poster.before_loop
    async def _before_daily(self):
        await self.bot.wait_until_ready()

    def _pick_poster(self, last_slug: str | None) -> dict:
        choices = [p for p in POSTERS if p["slug"] != last_slug]
        return random.choice(choices)

    async def _send_daily(self, channel: discord.TextChannel, guild_id: int, last_slug: str | None):
        poster = self._pick_poster(last_slug)
        try:
            msg = await channel.send(embed=_build_embed(poster))
        except discord.Forbidden:
            return
        try:
            await msg.add_reaction(HEART)
            await msg.add_reaction(RAGE)
        except discord.Forbidden:
            pass
        await self.db.set_poster_last(guild_id, poster["slug"])
        await self.db.log_poster_message(guild_id, channel.id, msg.id)


async def setup(bot: commands.Bot):
    await bot.add_cog(PostersScheduler(bot))
