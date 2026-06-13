import time
import discord
from discord import app_commands
from discord.ext import commands

COOLDOWN_SECONDS = 86400
ENDORSE_DELTA = 3.0
REBUKE_DELTA = -3.0


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
            await interaction.response.send_message("Invalid target.", ephemeral=True)
            return

        await interaction.response.defer()

        existing = await self.db.get_endorsement(gid, uid, target.id)
        if existing and (int(time.time()) - existing["timestamp"]) < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (int(time.time()) - existing["timestamp"])
            hours, mins = divmod(remaining // 60, 60)
            await interaction.followup.send(
                f"You have already rated this citizen. Cooldown: {hours}h {mins}m remaining.",
                ephemeral=True,
            )
            return

        await self.db.set_endorsement(gid, uid, target.id, etype)
        delta = ENDORSE_DELTA if etype == "endorse" else REBUKE_DELTA
        score_reason = f"citizen {etype}ment" + (f": {reason}" if reason else "")
        _, new_score = await self.db.update_score(gid, target.id, delta, score_reason)
        await self.db.update_social_counts(gid, target.id, uid, etype)

        if etype == "endorse":
            color = 0xFFD700
            title_action = "公民背书  ·  CITIZEN ENDORSED"
            footer = "The bureau acknowledges this commendation."
        else:
            color = 0xCC0000
            title_action = "公民谴责  ·  CITIZEN REBUKED"
            footer = "This dissatisfaction has been logged."

        embed = discord.Embed(color=color, title="中华人民共和国社会信用局")
        embed.add_field(name=title_action, value=target.mention, inline=False)
        embed.add_field(name="SCORE IMPACT", value=f"{delta:+.2f}  ->  {new_score:.2f}", inline=True)
        if reason:
            embed.add_field(name="REASON", value=reason[:200], inline=False)
        embed.set_footer(text=footer)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="endorse", description="Endorse a citizen (once per 24 hours per citizen)")
    @app_commands.describe(citizen="Citizen to endorse", reason="Optional reason")
    async def endorse(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "endorse", reason)

    @app_commands.command(name="rebuke", description="Rebuke a citizen (once per 24 hours per citizen)")
    @app_commands.describe(citizen="Citizen to rebuke", reason="Optional reason")
    async def rebuke(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "rebuke", reason)


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
