import discord
from discord.ext import commands
from config.ranks import get_rank


class Admin(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @commands.command(name="initialize")
    @commands.has_permissions(manage_guild=True)
    async def initialize(self, ctx):
        async with ctx.typing():
            members = [m for m in ctx.guild.members if not m.bot]
            member_ids = [m.id for m in members]
            await self.db.register_guild_members(ctx.guild.id, member_ids)
        await ctx.send(f"{len(member_ids)} citizens registered.")

    @commands.command(name="adjust")
    @commands.has_permissions(manage_guild=True)
    async def adjust_score(self, ctx, citizen: discord.Member, delta: float, *, reason: str):
        async with ctx.typing():
            gid = ctx.guild.id
            old, new = await self.db.update_score(gid, citizen.id, delta, f"manual adjustment: {reason}")
            old_rank, new_rank = get_rank(old), get_rank(new)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 手动调整")
            embed.add_field(name="CITIZEN",    value=str(citizen),             inline=False)
            embed.add_field(name="ADJUSTMENT", value=f"{delta:+.2f}",          inline=True)
            embed.add_field(name="SCORE",      value=f"{old:.2f} → {new:.2f}", inline=True)
            if old_rank["name"] != new_rank["name"]:
                embed.add_field(name="RANK CHANGE", value=f"{old_rank['name']} → {new_rank['name']}", inline=False)
            embed.add_field(name="REASON", value=reason, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def reset_citizen(self, ctx, citizen: discord.Member):
        async with ctx.typing():
            gid = ctx.guild.id
            user = await self.db.get_user(gid, citizen.id)
            delta = 750.0 - user["score"]
            await self.db.update_score(gid, citizen.id, delta, "bureau-mandated reset")
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="CITIZEN RESET", value=f"{citizen.mention} has been returned to baseline.", inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="threshold")
    @commands.has_permissions(manage_guild=True)
    async def set_threshold(self, ctx, n: int):
        if n < 1:
            await ctx.send("Threshold must be at least 1.")
            return
        async with ctx.typing():
            await self.db.set_confirm_threshold(ctx.guild.id, n)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="THRESHOLD UPDATED", value=f"Fundraiser verification now requires {n} votes.", inline=False)
        await ctx.send(embed=embed)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("Insufficient clearance.")
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`")
        elif isinstance(error, commands.BadArgument):
            await ctx.send("Invalid argument.")


async def setup(bot: commands.Bot):
    await bot.add_cog(Admin(bot))
