import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement


class CheckIn(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="checkin", description="Perform your daily check-in for Yuan and score")
    async def checkin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = interaction.user.id

        result = await self.db.do_checkin(gid, uid)
        if result is None:
            await interaction.followup.send("You are not registered in the system.", ephemeral=True)
            return

        if result["already_checked_in"]:
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 日常汇报")
            embed.add_field(
                name="ALREADY REPORTED",
                value="You have already completed your daily check-in. Return tomorrow.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        streak = result["streak"]
        yuan   = result["yuan_reward"]
        delta  = result["score_delta"]
        old    = result["old_score"]
        new    = result["new_score"]

        next_yuan  = min(250 + streak * 100, 2000)
        next_score = round(min(2.0 + streak * 0.1, 5.0), 2)
        at_cap     = yuan >= 2000 and delta >= 5.0

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 日常汇报")
        embed.add_field(name="CHECK-IN RECORDED", value=f"Day {streak} streak", inline=False)
        embed.add_field(name="YUAN AWARDED",      value=f"¥{yuan:,}",           inline=True)
        embed.add_field(name="SCORE",             value=f"{old:.2f} -> {new:.2f} (+{delta})", inline=True)
        if streak > 1:
            if at_cap:
                bonus_text = f"Maximum loyalty rewards reached · ¥{yuan:,} · +{delta} score per check-in"
            else:
                bonus_text = f"Tomorrow: ¥{next_yuan:,} · +{next_score} score"
            embed.add_field(name="STREAK BONUS", value=bonus_text, inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)

        self.bot.dispatch("score_change", interaction.guild, interaction.user, interaction.channel, old, new)

        if streak >= 100:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_100", channel=interaction.channel)
        elif streak >= 30:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_30", channel=interaction.channel)
        elif streak >= 7:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "checkin_streak_7", channel=interaction.channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(CheckIn(bot))
