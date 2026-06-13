import discord
from discord import app_commands
from discord.ext import commands


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
        yuan = result["yuan_reward"]
        old = result["old_score"]
        new = result["new_score"]

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 日常汇报")
        embed.add_field(name="CHECK-IN RECORDED", value=f"Day {streak} streak", inline=False)
        embed.add_field(name="YUAN AWARDED", value=f"¥{yuan}", inline=True)
        embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
        if streak > 1:
            embed.add_field(
                name="STREAK BONUS",
                value="Continued loyalty earns increased rewards. Maintain your streak for maximum benefit.",
                inline=False,
            )
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CheckIn(bot))
