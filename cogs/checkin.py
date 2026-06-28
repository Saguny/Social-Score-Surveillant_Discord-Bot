import random
import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement
from infra.guild_notify import publish_guild_notify

_CENSUS_EVENTS = [
    # (weight, colour, flavour)
    (8, 0xFFD700, "Inspection passed. Citizen record is satisfactory."),
    (8, 0xFFD700, "Bureau found evidence of model productivity. Bonus disbursed."),
    (8, 0xFFD700, "State subsidy approved. Loyalty index updated favorably."),
    (8, 0xFFD700, "Neighbor filed a positive report. Commendation noted."),
    (8, 0xFFD700, "Productivity report exceeded quarterly expectations."),
    (8, 0xCC0000, "Census logged. You have been counted. Continue."),
    (8, 0xCC0000, "Routine inspection completed. Nothing of note."),
    (8, 0xCC0000, "Bureau acknowledges your continued existence."),
    (8, 0xCC0000, "File reviewed. No action required at this time."),
    (8, 0xCC0000, "Daily census confirmed. Allocation processed."),
    (4, 0x888888, "Bureau detected accounting irregularities. Allocation unaffected."),
    (4, 0x888888, "Inspection revealed minor compliance failures. Noted for the record."),
    (4, 0x888888, "Anonymous report filed against this citizen. Under review."),
    (4, 0x888888, "Suspicious patterns detected in citizen activity log. Monitoring continues."),
]

_WEIGHTS = [e[0] for e in _CENSUS_EVENTS]


def _roll_event() -> tuple[int, str]:
    event = random.choices(_CENSUS_EVENTS, weights=_WEIGHTS, k=1)[0]
    return event[1], event[2]


def _fallback_channel(guild: discord.Guild) -> discord.TextChannel | None:
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
    return next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)


class CheckIn(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="checkin", description="Daily check-in for Yuan and score, applied in every server you share with the bureau")
    async def checkin(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = interaction.user.id
        guild_ids = await self.db.get_user_guild_ids(uid)

        if not guild_ids:
            await interaction.followup.send("You are not registered in the system.", ephemeral=True)
            return

        result = await self.db.do_checkin(uid, guild_ids)

        if result["already_checked_in"]:
            embed = discord.Embed(color=0x888888, title="CENSUS ALREADY LOGGED", description="中华人民共和国社会信用局")
            embed.add_field(name="COMPLIANCE", value="Census recorded today. Report again tomorrow.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        streak   = result["streak"]
        yuan     = result["yuan_reward"]
        delta    = result["score_delta"]
        rewarded = result["guilds_rewarded"]

        next_yuan  = min(250 + streak * 100, 2000)
        next_score = round(min(2.0 + streak * 0.1, 5.0), 2)
        at_cap     = yuan >= 2000 and delta >= 5.0

        event_color, event_text = _roll_event()

        embed = discord.Embed(color=event_color, title="DAILY CENSUS RECORDED", description="中华人民共和国社会信用局")
        embed.add_field(name="BUREAU REPORT", value=event_text, inline=False)
        embed.add_field(name="STREAK", value=f"Day {streak}", inline=True)
        embed.add_field(name="ALLOCATION", value=f"¥{yuan:,} · +{delta:.2f} rating · {rewarded} nations", inline=True)
        if at_cap:
            embed.add_field(name="NEXT", value="Maximum allocation reached.", inline=False)
        elif streak > 1:
            embed.add_field(name="NEXT", value=f"¥{next_yuan:,} · +{next_score:.2f}", inline=False)
        embed.set_thumbnail(url="attachment://checkin.png")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, file=discord.File("images/checkin.png", filename="checkin.png"))

        for gr in result["guild_results"]:
            guild = self.bot.get_guild(gr["guild_id"])
            member = guild.get_member(uid) if guild else None
            if guild and member:
                self.bot.dispatch("score_change", guild, member, _fallback_channel(guild), gr["old_score"], gr["new_score"])
            else:
                await publish_guild_notify(gr["guild_id"], "checkin_score_change", {
                    "user_id": uid, "old_score": gr["old_score"], "new_score": gr["new_score"],
                })

        if streak >= 100:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_100", channel=interaction.channel)
        elif streak >= 30:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_30", channel=interaction.channel)
        elif streak >= 7:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_7", channel=interaction.channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(CheckIn(bot))
