import random
import datetime
import discord
from discord.ext import commands, tasks
from config.poster_data import POSTERS

HEART = "❤️"
RAGE  = "😡"

HEART_YUAN  = 250
HEART_SCORE = 3.0
RAGE_SCORE  = -1.0


def _build_embed(poster: dict) -> discord.Embed:
    title = poster["title_zh"] or poster["title"]
    embed = discord.Embed(color=0xCC0000, title=title, url=poster["page_url"])

    date_parts = []
    if poster["year"]:
        date_parts.append(poster["year"])
    if poster["theme"]:
        date_parts.append(poster["theme"])
    if date_parts:
        embed.description = " · ".join(date_parts)

    embed.set_image(url=poster["image_url"])

    if poster["designer"]:
        embed.add_field(name="Designer", value=poster["designer"], inline=True)

    if poster["description"]:
        embed.add_field(name="Context", value=poster["description"], inline=False)

    credit = poster["call_number"] or "chineseposters.net"
    if poster["collection"]:
        credit += f" · {poster['collection']}"
    embed.set_footer(text=f"{credit} · chineseposters.net · GLORY TO THE CCP!")
    return embed


class Posters(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db  = bot.db
        self._active: dict[int, dict] = {}

    async def cog_load(self):
        guilds = await self.db.get_poster_guilds()
        for row in guilds:
            self._active[row["guild_id"]] = {
                "channel_id": row["channel_id"],
                "last_slug":  row["last_slug"],
            }
        self._daily_poster.start()

    async def cog_unload(self):
        self._daily_poster.cancel()

    @tasks.loop(time=datetime.time(hour=12, minute=0, tzinfo=datetime.timezone.utc))
    async def _daily_poster(self):
        for guild_id, cfg in list(self._active.items()):
            channel = self.bot.get_channel(cfg["channel_id"])
            if not channel:
                continue
            await self._send_daily(channel, guild_id)

    @_daily_poster.before_loop
    async def _before_daily(self):
        await self.bot.wait_until_ready()

    def _pick_poster(self, last_slug: str | None) -> dict:
        choices = [p for p in POSTERS if p["slug"] != last_slug]
        return random.choice(choices)

    async def _send_daily(self, channel: discord.TextChannel, guild_id: int):
        poster = self._pick_poster(self._active[guild_id].get("last_slug"))
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
        self._active[guild_id]["last_slug"] = poster["slug"]
        await self.db.log_poster_message(guild_id, channel.id, msg.id)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if payload.guild_id not in self._active:
            return
        row = await self.db.get_poster_message(payload.guild_id, payload.message_id)
        if not row:
            return
        emoji = str(payload.emoji)
        if emoji not in (HEART, RAGE):
            return
        gid, uid = payload.guild_id, payload.user_id
        if not await self.db.record_poster_reaction(payload.message_id, uid):
            return
        if emoji == HEART:
            await self.db.tick_user(gid, uid, HEART_YUAN)
            await self.db.update_score(gid, uid, HEART_SCORE, "propaganda poster: supported")
        else:
            await self.db.update_score(gid, uid, RAGE_SCORE, "propaganda poster: resisted")

    @commands.command(name="poster")
    async def show_poster(self, ctx: commands.Context):
        async with ctx.typing():
            last = self._active.get(ctx.guild.id, {}).get("last_slug")
            poster = self._pick_poster(last)
            await ctx.send(embed=_build_embed(poster))

    @commands.command(name="posters")
    @commands.has_permissions(manage_guild=True)
    async def toggle_posters(self, ctx: commands.Context):
        async with ctx.typing():
            gid = ctx.guild.id
            if gid in self._active:
                await self.db.disable_posters(gid)
                del self._active[gid]
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
                embed.add_field(name="PROPAGANDA BROADCAST · DISABLED", value="Daily posters have been suspended.", inline=False)
                await ctx.send(embed=embed)
            else:
                channel = ctx.channel
                await self.db.enable_posters(gid, channel.id)
                self._active[gid] = {"channel_id": channel.id, "last_slug": None}
                embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
                now = datetime.datetime.now(datetime.timezone.utc)
                next_noon = now.replace(hour=12, minute=0, second=0, microsecond=0)
                if now >= next_noon:
                    next_noon += datetime.timedelta(days=1)
                ts = int(next_noon.timestamp())
                embed.add_field(
                    name="PROPAGANDA BROADCAST · ENABLED",
                    value=f"Daily posters will be sent to {channel.mention} at <t:{ts}:t> every day.",
                    inline=False,
                )
                await ctx.send(embed=embed)


async def setup(bot: commands.Bot):
    await bot.add_cog(Posters(bot))
