import os
import aiohttp
import discord
from discord.ext import commands, tasks

VOTE_URL = "https://top.gg/bot/856163780265902151/vote"
TOPGG_BOT_ID = "856163780265902151"
TOPGG_STATS_URL = f"https://top.gg/api/bots/{TOPGG_BOT_ID}/stats"


class VotingScheduler(commands.Cog):
    """Background vote-reminder and top.gg stats-posting loops.

    No app_commands live here -- /vote stays on cogs.voting.Voting (gateway
    workers). process_vote (the top.gg webhook entry point) also stays a
    module-level function in cogs.voting, called directly by web/server.py
    wherever the web service is running, not through this cog.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self._check_reminders.start()
        self._post_stats.start()

    async def cog_unload(self):
        self._check_reminders.cancel()
        self._post_stats.cancel()

    @tasks.loop(minutes=5)
    async def _check_reminders(self):
        await self.db.clean_expired_cosmetic_badges()
        user_ids = await self.db.get_due_vote_reminders()
        for user_id in user_ids:
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(
                name="VOTE REMINDER",
                value="You may now vote for this bot on Top.gg again. Your continued loyalty is noted.",
                inline=False,
            )
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label="Vote", style=discord.ButtonStyle.link, url=VOTE_URL))
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed, view=view)
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

    @_check_reminders.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=30)
    async def _post_stats(self):
        token = os.getenv("TOPGG_TOKEN", "")
        if not token:
            return
        server_count = len(self.bot.guilds)
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    TOPGG_STATS_URL,
                    headers={"Authorization": token},
                    json={"server_count": server_count},
                )
        except aiohttp.ClientError:
            pass

    @_post_stats.before_loop
    async def _before_post_stats(self):
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot):
    await bot.add_cog(VotingScheduler(bot))
