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
            embed.add_field(name="SCORE",      value=f"{old:.2f} -> {new:.2f}", inline=True)
            if old_rank["name"] != new_rank["name"]:
                embed.add_field(name="RANK CHANGE", value=f"{old_rank['name']} -> {new_rank['name']}", inline=False)
            embed.add_field(name="REASON", value=reason, inline=False)
        await ctx.send(embed=embed)
        self.bot.dispatch("score_change", ctx.guild, citizen, ctx.channel, old, new)

    @commands.command(name="reset")
    @commands.has_permissions(manage_guild=True)
    async def reset_citizen(self, ctx, citizen: discord.Member):
        async with ctx.typing():
            gid = ctx.guild.id
            user = await self.db.get_user(gid, citizen.id)
            delta = 750.0 - user["score"]
            old, new = await self.db.update_score(gid, citizen.id, delta, "bureau-mandated reset")
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="CITIZEN RESET", value=f"{citizen.mention} has been returned to baseline.", inline=False)
        await ctx.send(embed=embed)
        self.bot.dispatch("score_change", ctx.guild, citizen, ctx.channel, old, new)

    @commands.command(name="executions")
    @commands.has_permissions(manage_guild=True)
    async def set_execution_channel(self, ctx, channel: discord.TextChannel = None):
        async with ctx.typing():
            await self.db.set_execution_channel(ctx.guild.id, channel.id if channel else None)
            msg = f"Execution notices will be posted in {channel.mention}." if channel else "Execution channel cleared · notices will post in message channel."
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="EXECUTION CHANNEL", value=msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="achievements_channel")
    @commands.has_permissions(manage_guild=True)
    async def set_achievements_channel(self, ctx, channel_arg: str = None):
        async with ctx.typing():
            if channel_arg is None:
                await self.db.set_achievements_channel(ctx.guild.id, None)
                await self.db.set_achievements_loud_enabled(ctx.guild.id, True)
                msg = "Achievements channel cleared · loud unlocks will post in the triggering channel."
            elif channel_arg.lower() in ("off", "disable", "false", "no"):
                await self.db.set_achievements_loud_enabled(ctx.guild.id, False)
                msg = "Loud achievement announcements disabled · check `/achievements` to view unlocks."
            else:
                try:
                    channel = await commands.TextChannelConverter().convert(ctx, channel_arg)
                except commands.BadArgument:
                    await ctx.send("Usage: `ccp achievements_channel [#channel|off]`")
                    return
                await self.db.set_achievements_channel(ctx.guild.id, channel.id)
                await self.db.set_achievements_loud_enabled(ctx.guild.id, True)
                msg = f"Rare achievement announcements will be posted in {channel.mention}."
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="ACHIEVEMENTS CHANNEL", value=msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="roles")
    @commands.has_permissions(manage_guild=True)
    async def toggle_rank_roles(self, ctx, state: str = None):
        async with ctx.typing():
            current = await self.db.get_assign_rank_roles(ctx.guild.id)
            if state is None:
                enabled = not current
            elif state.lower() in ("on", "enable", "true", "yes"):
                enabled = True
            elif state.lower() in ("off", "disable", "false", "no"):
                enabled = False
            else:
                await ctx.send("Usage: `ccp roles [on|off]`")
                return
            await self.db.set_assign_rank_roles(ctx.guild.id, enabled)
            status = "ENABLED" if enabled else "DISABLED"
            note = (
                "The bot will automatically create and assign Discord server roles matching each rank tier."
                if enabled else
                "Rank tiers are tracked internally only. No Discord roles will be created or assigned."
            )
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name=f"RANK ROLES · {status}", value=note, inline=False)
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
