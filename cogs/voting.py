import asyncio
import os
import random
import time
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from cogs.achievements import unlock as unlock_achievement, check_milestone

VOTE_URL = "https://top.gg/bot/856163780265902151/vote"
TOPGG_BOT_ID = "856163780265902151"
TOPGG_STATS_URL = f"https://top.gg/api/bots/{TOPGG_BOT_ID}/stats"
VOTE_SCORE_BASE = 2.0
VOTE_YUAN_BASE = 1500
VOTE_STREAK_YUAN_STEP = 150
VOTE_STREAK_YUAN_CAP = 4500
VOTE_STREAK_SCORE_STEP = 0.05
VOTE_STREAK_SCORE_CAP = 4.0
VOTE_WEEKEND_MULTIPLIER = 2
VOTE_CHECKIN_COMBO_YUAN = 500
VOTE_CHECKIN_COMBO_SCORE = 0.5
VOTE_BADGE = "voter"
VOTE_COOLDOWN = 12 * 60 * 60

_VOTE_VARIANCE_TIERS = [
    (0.80, 1.0),
    (0.15, 1.5),
    (0.05, 2.5),
]


def _roll_vote_multiplier() -> float:
    r = random.random()
    cumulative = 0.0
    for weight, mult in _VOTE_VARIANCE_TIERS:
        cumulative += weight
        if r < cumulative:
            return mult
    return 1.0

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
        remind_at = int(time.time()) + VOTE_COOLDOWN
        await self.db.set_vote_reminder(self.user_id, remind_at)
        try:
            await interaction.response.edit_message(content=f"The bureau will remind you to vote again <t:{remind_at}:R> (<t:{remind_at}:f>).", embed=None, view=self)
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


async def _reward_guild(
    bot, db, guild, user_id: int, expires_at: int, total_votes: int, vote_streak: int,
    yuan_reward: int, score_delta: float,
) -> tuple[str, bool] | None:
    member = guild.get_member(user_id)
    if not member:
        return None
    combo = False
    user_row = await db.get_user(guild.id, user_id)
    if user_row:
        now = int(time.time())
        today_start = now - (now % 86400)
        if user_row["last_checkin"] >= today_start:
            combo = True
    final_yuan = yuan_reward + (VOTE_CHECKIN_COMBO_YUAN if combo else 0)
    final_score = round(score_delta + (VOTE_CHECKIN_COMBO_SCORE if combo else 0), 2)
    await asyncio.gather(
        db.update_score(guild.id, user_id, final_score, "topgg vote"),
        db.adjust_yuan(guild.id, user_id, final_yuan),
    )
    await unlock_achievement(bot, guild, member, "first_vote")
    await check_milestone(bot, guild, member, "topgg_votes_total", total_votes)
    await check_milestone(bot, guild, member, "topgg_vote_streak", vote_streak)
    return guild.name, combo


async def process_vote(bot: commands.Bot, user_id: int):
    db = bot.db
    await db.log_topgg_vote(user_id)
    total_votes = await db.increment_counter(user_id, "topgg_votes_total")
    vote_streak, _ = await db.bump_daily_streak(user_id, "topgg_vote_streak")
    expires_at = int(time.time()) + VOTE_COOLDOWN

    yuan_base = min(VOTE_YUAN_BASE + (vote_streak - 1) * VOTE_STREAK_YUAN_STEP, VOTE_STREAK_YUAN_CAP)
    score_base = min(VOTE_SCORE_BASE + (vote_streak - 1) * VOTE_STREAK_SCORE_STEP, VOTE_STREAK_SCORE_CAP)
    multiplier = _roll_vote_multiplier()
    yuan_reward = round(yuan_base * multiplier)
    score_delta = round(score_base * multiplier, 2)

    is_weekend = time.gmtime().tm_wday >= 5
    if is_weekend:
        yuan_reward *= VOTE_WEEKEND_MULTIPLIER
        score_delta = round(score_delta * VOTE_WEEKEND_MULTIPLIER, 2)

    results = await asyncio.gather(
        *(_reward_guild(bot, db, guild, user_id, expires_at, total_votes, vote_streak, yuan_reward, score_delta) for guild in bot.guilds)
    )
    rewarded = [r for r in results if r is not None]
    rewarded_guilds = [name for name, _ in rewarded]
    any_combo = any(combo for _, combo in rewarded)
    print(f"[topgg vote] user {user_id} rewarded in {len(rewarded_guilds)}/{len(bot.guilds)} guilds: {rewarded_guilds}")

    if not rewarded_guilds:
        print(f"[topgg vote] user {user_id} not a cached member of any guild, no DM sent")
        return

    await db.add_temporary_cosmetic_badge(user_id, VOTE_BADGE, expires_at)

    lines = [
        f"Your vote has been logged with the bureau. You have received +¥{yuan_reward:,}, "
        f"+{score_delta:.2f} score, and the Loyal Patriot badge (12h) on every server you share with "
        f"this bot ({len(rewarded_guilds)} total). This reward applies per server · once per vote."
    ]
    if is_weekend:
        lines.append("🎉 Weekend bonus: rewards doubled today.")
    if multiplier > 1.0:
        lines.append(f"🎲 Lucky roll: a {multiplier:.1f}x bonus was applied.")
    if vote_streak > 1:
        lines.append(f"🔥 Vote streak: {vote_streak} days in a row.")
    if any_combo:
        lines.append(
            f"✅ Checked in today too — an extra +¥{VOTE_CHECKIN_COMBO_YUAN:,} / +{VOTE_CHECKIN_COMBO_SCORE:.2f} "
            f"combo bonus was applied in the server(s) where you checked in."
        )

    embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
    embed.add_field(
        name="VOTE RECEIVED · THANK YOU, COMRADE",
        value="\n".join(lines),
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

    async def cog_load(self):
        self._check_reminders.start()
        self._post_stats.start()

    async def cog_unload(self):
        self._check_reminders.cancel()
        self._post_stats.cancel()

    @app_commands.command(name="vote", description="Vote for this bot on Top.gg for a badge, score, and yuan")
    async def vote(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CALL TO PATRIOTIC DUTY")
        embed.add_field(
            name="VOTE FOR THE BUREAU",
            value=(
                "Cast your ballot for this bot on Top.gg to receive a badge, score, and yuan "
                "on every server you share with the bureau. Rewards scale with your vote streak, "
                "carry a chance of a lucky bonus roll, are doubled on weekends, and stack further "
                "if you've also checked in today. You can vote again every 12 hours."
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
    await bot.add_cog(Voting(bot))
