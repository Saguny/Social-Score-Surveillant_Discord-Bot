import time
import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement, check_milestone

COOLDOWN_SECONDS = 86400
ENDORSE_DELTA = 1.5
REBUKE_DELTA = -1.5


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def _rate(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        etype: str,
        reason: str | None = None,
    ):
        gid = interaction.guild.id
        uid = interaction.user.id

        if target.bot or target.id == uid:
            embed = discord.Embed(color=0x888888, title="REQUEST DENIED", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value="The Bureau does not permit citizens to file ratings against themselves or automated accounts.", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        existing = await self.db.get_endorsement(gid, uid, target.id)
        if existing and (int(time.time()) - existing["timestamp"]) < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (int(time.time()) - existing["timestamp"])
            hours, mins = divmod(remaining // 60, 60)
            embed = discord.Embed(color=0x888888, title="ACTION UNAVAILABLE", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value=f"This citizen has already been rated. Bureau records indicate {hours}h {mins}m must pass before re-evaluation.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await self.db.set_endorsement(gid, uid, target.id, etype)
        delta = ENDORSE_DELTA if etype == "endorse" else REBUKE_DELTA
        delta, _ = await self.db.apply_defense_chain(gid, target.id, delta)
        score_reason = f"citizen {etype}ment" + (f": {reason}" if reason else "")
        old_score, new_score = await self.db.update_score(gid, target.id, delta, score_reason)
        await self.db.update_social_counts(gid, target.id, uid, etype)

        if etype == "endorse":
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_endorsement", channel=interaction.channel)
            streak, _ = await self.db.bump_daily_streak(uid, "endorse_streak")
            await check_milestone(self.bot, interaction.guild, interaction.user, "endorse_streak", streak, channel=interaction.channel)
        else:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_rebuke", channel=interaction.channel)
            streak, _ = await self.db.bump_daily_streak(uid, "rebuke_streak")
            await check_milestone(self.bot, interaction.guild, interaction.user, "rebuke_streak", streak, channel=interaction.channel)
            if delta < 0:
                await self.db.record_negative_action(target.id)

        self.bot.dispatch("score_change", interaction.guild, target, interaction.channel, old_score, new_score)

        if etype == "endorse":
            embed = discord.Embed(color=0xFFD700, title="COMMENDATION FILED", description="中华人民共和国社会信用局")
            embed.set_author(name="The Bureau · Dept. of Citizen Affairs")
            embed.add_field(name="SUBJECT", value=target.mention, inline=True)
            embed.add_field(name="FILED BY", value=interaction.user.mention, inline=True)
            embed.add_field(name="RATING", value=f"{old_score:.2f} -> {new_score:.2f}  ({delta:+.2f})", inline=False)
        else:
            embed = discord.Embed(color=0xCC0000, title="CENSURE FILED", description="中华人民共和国社会信用局")
            embed.set_author(name="The Bureau · Dept. of Citizen Affairs")
            embed.add_field(name="SUBJECT", value=target.mention, inline=True)
            embed.add_field(name="FILED BY", value=interaction.user.mention, inline=True)
            embed.add_field(name="RATING", value=f"{old_score:.2f} -> {new_score:.2f}  ({delta:+.2f})", inline=False)

        if reason:
            embed.add_field(name="STATEMENT", value=reason[:200], inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="endorse", description="Commend a citizen's conduct (once per 24h per citizen)")
    @app_commands.describe(citizen="Citizen to commend", reason="Optional statement for the record")
    async def endorse(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "endorse", reason)

    @app_commands.command(name="rebuke", description="File a censure against a citizen (once per 24h per citizen)")
    @app_commands.describe(citizen="Citizen to censure", reason="Optional statement for the record")
    async def rebuke(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "rebuke", reason)


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
