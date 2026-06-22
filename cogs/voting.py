import asyncio
import os
import time
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from cogs.achievements import unlock as unlock_achievement

VOTE_URL = "https://top.gg/bot/856163780265902151/vote"
TOPGG_BOT_ID = "856163780265902151"
TOPGG_STATS_URL = f"https://top.gg/api/bots/{TOPGG_BOT_ID}/stats"
VOTE_SCORE_DELTA = 2.0
VOTE_YUAN_REWARD = 1500
VOTE_BADGE = "voter"
VOTE_COOLDOWN = 12 * 60 * 60

_PRESENCE_CYCLE = [
    discord.Activity(type=discord.ActivityType.watching, name="/guide | /shop"),
    discord.Activity(type=discord.ActivityType.watching, name="/vote | /checkin"),
    discord.Activity(type=discord.ActivityType.watching, name="/botinfo"),
]


class VoteReminderView(discord.ui.View):
    def __init__(self, user_id: int, db):
        super().__init__(timeout=300)
        self.user_id = user_id
        self.db = db
        self.done = False

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("This is not your reminder to set.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Remind Me", style=discord.ButtonStyle.success)
    async def yes(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return
        self.done = True
        self.clear_items()
        await self.db.set_vote_reminder(self.user_id, int(time.time()) + VOTE_COOLDOWN)
        try:
            await interaction.response.edit_message(content="The bureau will remind you to vote again in 12 hours.", embed=None, view=self)
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Don't Remind Me", style=discord.ButtonStyle.danger)
    async def no(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.done:
            return
        self.done = True
        self.clear_items()
        try:
            await interaction.response.edit_message(content="Understood, citizen.", embed=None, view=self)
        except discord.HTTPException:
            pass


async def _reward_guild(bot, db, guild, user_id: int, expires_at: int) -> str | None:
    member = guild.get_member(user_id)
    if not member:
        return None
    await asyncio.gather(
        db.update_score(guild.id, user_id, VOTE_SCORE_DELTA, "topgg vote"),
        db.adjust_yuan(guild.id, user_id, VOTE_YUAN_REWARD),
    )
    await unlock_achievement(bot, guild, member, "first_vote")
    return guild.name


async def process_vote(bot: commands.Bot, user_id: int):
    db = bot.db
    await db.log_topgg_vote(user_id)
    expires_at = int(time.time()) + VOTE_COOLDOWN
    results = await asyncio.gather(
        *(_reward_guild(bot, db, guild, user_id, expires_at) for guild in bot.guilds)
    )
    rewarded_guilds = [name for name in results if name is not None]
    print(f"[topgg vote] user {user_id} rewarded in {len(rewarded_guilds)}/{len(bot.guilds)} guilds: {rewarded_guilds}")

    if not rewarded_guilds:
        print(f"[topgg vote] user {user_id} not a cached member of any guild, no DM sent")
        return

    await db.add_temporary_cosmetic_badge(user_id, VOTE_BADGE, expires_at)

    embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
    embed.add_field(
        name="VOTE RECEIVED · THANK YOU, COMRADE",
        value=(
            f"Your vote has been logged with the bureau. You have received +¥{VOTE_YUAN_REWARD:,}, "
            f"+{VOTE_SCORE_DELTA:.2f} score, and the Loyal Patriot badge (12h) on every server you share with "
            f"this bot ({len(rewarded_guilds)} total). This reward applies globally · once per vote."
        ),
        inline=False,
    )

    try:
        user = await bot.fetch_user(user_id)
        await user.send(embed=embed, view=VoteReminderView(user_id, db))
    except discord.Forbidden:
        pass
    except discord.HTTPException:
        pass


class Voting(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._presence_index = 0

    async def cog_load(self):
        self._check_reminders.start()
        self._rotate_presence.start()
        self._post_stats.start()

    async def cog_unload(self):
        self._check_reminders.cancel()
        self._rotate_presence.cancel()
        self._post_stats.cancel()

    @app_commands.command(name="vote", description="Vote for this bot on Top.gg for a badge, score, and yuan")
    async def vote(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CALL TO PATRIOTIC DUTY")
        embed.add_field(
            name="VOTE FOR THE BUREAU",
            value=(
                "Cast your ballot for this bot on Top.gg to receive a badge, "
                "+2.00 score, and ¥1,500 yuan on every server you share with the bureau. "
                "You can vote again every 12 hours."
            ),
            inline=False,
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Vote on Top.gg", style=discord.ButtonStyle.link, url=VOTE_URL))
        await interaction.followup.send(embed=embed, view=view)

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
            try:
                user = await self.bot.fetch_user(user_id)
                await user.send(embed=embed)
            except discord.Forbidden:
                continue
            except discord.HTTPException:
                continue

    @_check_reminders.before_loop
    async def _before_check(self):
        await self.bot.wait_until_ready()

    @tasks.loop(minutes=10)
    async def _rotate_presence(self):
        self._presence_index = (self._presence_index + 1) % len(_PRESENCE_CYCLE)
        await self.bot.change_presence(activity=_PRESENCE_CYCLE[self._presence_index])

    @_rotate_presence.before_loop
    async def _before_rotate(self):
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
    await bot.add_cog(Voting(bot))
