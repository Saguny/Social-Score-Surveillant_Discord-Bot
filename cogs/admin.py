import asyncio
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

    @commands.command(name="rankchannel")
    @commands.has_permissions(manage_guild=True)
    async def set_rank_announcement_channel(self, ctx, channel: discord.TextChannel = None):
        async with ctx.typing():
            await self.db.set_rank_announcement_channel(ctx.guild.id, channel.id if channel else None)
            msg = f"Rank-up and demotion announcements will be posted in {channel.mention}." if channel else "Rank announcement channel cleared · notices will post in the message channel."
            embed = discord.Embed(color=0xCC0000, title="BUREAU DIRECTIVE", description="中华人民共和国社会信用局")
            embed.add_field(name="RANK ANNOUNCEMENT CHANNEL", value=msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="executions")
    @commands.has_permissions(manage_guild=True)
    async def set_execution_channel(self, ctx, channel: discord.TextChannel = None):
        async with ctx.typing():
            await self.db.set_execution_channel(ctx.guild.id, channel.id if channel else None)
            msg = f"Execution notices will be posted in {channel.mention}." if channel else "Execution channel cleared · notices will post in message channel."
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="EXECUTION CHANNEL", value=msg, inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="achievementnotification")
    @commands.has_permissions(manage_guild=True)
    async def set_achievement_notifications(self, ctx, state: str = None):
        async with ctx.typing():
            current = await self.db.get_achievements_loud_enabled(ctx.guild.id)
            if state is None:
                enabled = not current
            elif state.lower() in ("on", "enable", "true", "yes"):
                enabled = True
            elif state.lower() in ("off", "disable", "false", "no"):
                enabled = False
            else:
                await ctx.send("Usage: `ccp achievementnotification [on|off]`")
                return
            await self.db.set_achievements_loud_enabled(ctx.guild.id, enabled)
            msg = "Achievement unlock announcements enabled." if enabled else "Achievement unlock announcements disabled · check `/achievements` to view unlocks."
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="ACHIEVEMENT NOTIFICATIONS", value=msg, inline=False)
            embed.set_footer(text="ccp achievementnotification [on|off] · ccp achievementchannel [#channel]")
        await ctx.send(embed=embed)

    @commands.command(name="achievementchannel")
    @commands.has_permissions(manage_guild=True)
    async def set_achievement_channel(self, ctx, channel: discord.TextChannel = None):
        async with ctx.typing():
            await self.db.set_achievements_channel(ctx.guild.id, channel.id if channel else None)
            msg = f"Achievement unlocks will be announced in {channel.mention}." if channel else "Achievements channel cleared · unlocks will post in the triggering channel."
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="ACHIEVEMENT CHANNEL", value=msg, inline=False)
            embed.set_footer(text="ccp achievementnotification [on|off] · ccp achievementchannel [#channel]")
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

    @commands.command(name="settings")
    @commands.has_permissions(manage_guild=True)
    async def show_settings(self, ctx):
        async with ctx.typing():
            (
                exec_ch_id, rank_ch_id, score_log_ch_id,
                rank_roles, ach_loud, ach_ch_id,
                threshold, leaderboard_visible, poster_rows,
            ) = await asyncio.gather(
                self.db.get_execution_channel(ctx.guild.id),
                self.db.get_rank_announcement_channel(ctx.guild.id),
                self.db.get_score_log_channel(ctx.guild.id),
                self.db.get_assign_rank_roles(ctx.guild.id),
                self.db.get_achievements_loud_enabled(ctx.guild.id),
                self.db.get_achievements_channel(ctx.guild.id),
                self.db.get_confirm_threshold(ctx.guild.id),
                self.db.is_leaderboard_visible(ctx.guild.id),
                self.db._pool.fetch("SELECT channel_id FROM poster_config WHERE guild_id = $1", ctx.guild.id),
            )

            def ch(cid):
                if not cid:
                    return "not set"
                c = ctx.guild.get_channel(cid)
                return c.mention if c else f"<#{cid}> (deleted)"

            poster_ch_id = poster_rows[0]["channel_id"] if poster_rows else None

            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="CHANNELS", value=(
                f"Rank announcements · {ch(rank_ch_id)}\n"
                f"Execution notices · {ch(exec_ch_id)}\n"
                f"Score log · {ch(score_log_ch_id)}\n"
                f"Achievement announcements · {ch(ach_ch_id)}\n"
                f"Daily poster broadcast · {ch(poster_ch_id)}"
            ), inline=False)
            embed.add_field(name="TOGGLES", value=(
                f"Rank roles · {'on' if rank_roles else 'off'}\n"
                f"Achievement announcements · {'on' if ach_loud else 'off'}\n"
                f"Server leaderboard visible · {'on' if leaderboard_visible else 'off'}"
            ), inline=False)
            embed.add_field(name="OTHER", value=(
                f"Fundraiser vote threshold · {threshold or 3}"
            ), inline=False)
        await ctx.send(embed=embed)

    @commands.command(name="scorelog")
    @commands.has_permissions(manage_guild=True)
    async def set_score_log(self, ctx, *, arg: str = None):
        async with ctx.typing():
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            if arg is None or arg.lower() in ("off", "disable", "none"):
                await self.db.set_score_log_channel(ctx.guild.id, None)
                embed.add_field(name="SCORE LOG · DISABLED", value="Negative score events will no longer be logged.", inline=False)
            else:
                try:
                    channel = await commands.TextChannelConverter().convert(ctx, arg)
                except commands.BadArgument:
                    await ctx.send("Usage: `ccp scorelog #channel` or `ccp scorelog off`")
                    return
                await self.db.set_score_log_channel(ctx.guild.id, channel.id)
                embed.add_field(name="SCORE LOG · ENABLED", value=f"Negative score events will be posted to {channel.mention}.", inline=False)
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
