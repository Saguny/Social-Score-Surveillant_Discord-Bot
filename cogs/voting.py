import asyncio
import random
import time
import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement, check_milestone
from infra.guild_notify import publish_guild_notify

VOTE_URL = "https://top.gg/bot/856163780265902151/vote"
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


async def _apply_vote_reward_db(db, guild_id: int, user_id: int, yuan_reward: int, score_delta: float) -> bool:
    user_row = await db.get_user(guild_id, user_id)
    combo = False
    if user_row:
        now = int(time.time())
        today_start = now - (now % 86400)
        if user_row["last_checkin"] >= today_start:
            combo = True
    final_yuan = yuan_reward + (VOTE_CHECKIN_COMBO_YUAN if combo else 0)
    final_score = round(score_delta + (VOTE_CHECKIN_COMBO_SCORE if combo else 0), 2)
    await asyncio.gather(
        db.update_score(guild_id, user_id, final_score, "topgg vote"),
        db.adjust_yuan(guild_id, user_id, final_yuan),
    )
    return combo


async def _reward_guild_local(
    bot, db, guild, user_id: int, total_votes: int, vote_streak: int,
    yuan_reward: int, score_delta: float,
) -> tuple[str, bool] | None:
    member = guild.get_member(user_id)
    if not member:
        return None
    combo = await _apply_vote_reward_db(db, guild.id, user_id, yuan_reward, score_delta)
    await unlock_achievement(bot, guild, member, "first_vote")
    await check_milestone(bot, guild, member, "topgg_votes_total", total_votes)
    await check_milestone(bot, guild, member, "topgg_vote_streak", vote_streak)
    return guild.name, combo


async def _reward_guild_remote(
    db, guild_id: int, user_id: int, total_votes: int, vote_streak: int,
    yuan_reward: int, score_delta: float,
) -> tuple[str, bool]:
    combo = await _apply_vote_reward_db(db, guild_id, user_id, yuan_reward, score_delta)
    await publish_guild_notify(guild_id, "vote_achievement_check", {
        "user_id": user_id, "total_votes": total_votes, "vote_streak": vote_streak,
    })
    return f"guild {guild_id}", combo


async def _reward_guild(
    bot, db, guild_id: int, user_id: int, total_votes: int, vote_streak: int,
    yuan_reward: int, score_delta: float,
) -> tuple[str, bool] | None:
    guild = bot.get_guild(guild_id)
    if guild is not None:
        return await _reward_guild_local(bot, db, guild, user_id, total_votes, vote_streak, yuan_reward, score_delta)
    return await _reward_guild_remote(db, guild_id, user_id, total_votes, vote_streak, yuan_reward, score_delta)


async def process_vote(bot: commands.Bot, user_id: int):
    db = bot.db
    if await db.is_opted_out(user_id):
        print(f"[topgg vote] user {user_id} is opted out, ignoring vote")
        return
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

    guild_ids = await db.get_user_guild_ids(user_id)
    results = await asyncio.gather(
        *(_reward_guild(bot, db, gid, user_id, total_votes, vote_streak, yuan_reward, score_delta) for gid in guild_ids)
    )
    rewarded = [r for r in results if r is not None]
    rewarded_guilds = [name for name, _ in rewarded]
    any_combo = any(combo for _, combo in rewarded)
    print(f"[topgg vote] user {user_id} rewarded in {len(rewarded_guilds)}/{len(guild_ids)} guilds: {rewarded_guilds}")

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
            f"✅ Checked in today too, an extra +¥{VOTE_CHECKIN_COMBO_YUAN:,} / +{VOTE_CHECKIN_COMBO_SCORE:.2f} "
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

    @app_commands.command(name="vote", description="Vote for this bot on Top.gg for a badge, score, and yuan")
    async def vote(self, interaction: discord.Interaction):
        await interaction.response.defer()
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CALL TO PATRIOTIC DUTY")
        embed.add_field(
            name="BASE REWARD",
            value=f"¥{VOTE_YUAN_BASE:,} Yuan · +{VOTE_SCORE_BASE:.1f} Score · Loyal Patriot badge",
            inline=False,
        )
        embed.add_field(
            name="STREAK BONUS",
            value=f"Up to ¥{VOTE_STREAK_YUAN_CAP:,} · +{VOTE_STREAK_SCORE_CAP:.1f} score at max streak",
            inline=False,
        )
        if time.gmtime().tm_wday >= 5:
            embed.add_field(
                name="WEEKEND BONUS ACTIVE",
                value="2× all rewards right now · Today and tomorrow only",
                inline=False,
            )
        embed.add_field(
            name="STACKS WITH",
            value="Checkin combo · Lucky roll (up to 2.5×) · Every server you share with the bureau · Every 12 hours",
            inline=False,
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Vote on Top.gg", style=discord.ButtonStyle.link, url=VOTE_URL))
        await interaction.followup.send(embed=embed, view=view)


async def setup(bot: commands.Bot):
    await bot.add_cog(Voting(bot))
