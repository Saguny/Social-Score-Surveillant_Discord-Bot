import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement
from infra.guild_notify import publish_guild_notify


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
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 日常汇报")
            embed.add_field(
                name="ALREADY REPORTED",
                value="You have already completed your daily check-in. Return tomorrow.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        streak   = result["streak"]
        yuan     = result["yuan_reward"]
        delta    = result["score_delta"]
        rewarded = result["guilds_rewarded"]

        next_yuan  = min(250 + streak * 100, 2000)
        next_score = round(min(2.0 + streak * 0.1, 5.0), 2)
        at_cap     = yuan >= 2000 and delta >= 5.0

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 日常汇报")
        embed.add_field(name="CHECK-IN RECORDED", value=f"Day {streak} streak", inline=False)
        embed.add_field(name="YUAN AWARDED",      value=f"¥{yuan:,} per server ({rewarded} total)", inline=True)
        embed.add_field(name="SCORE",             value=f"+{delta:.2f} per server", inline=True)
        if streak > 1:
            if at_cap:
                bonus_text = f"Maximum loyalty rewards reached · ¥{yuan:,} · +{delta:.2f} score per check-in"
            else:
                bonus_text = f"Tomorrow: ¥{next_yuan:,} · +{next_score:.2f} score"
            embed.add_field(name="STREAK BONUS", value=bonus_text, inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed,)

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
