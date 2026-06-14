import discord
from discord import app_commands
from discord.ext import commands
from config.ranks import get_rank


class Stats(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="score", description="View a citizen's social credit score")
    @app_commands.describe(citizen="Citizen to look up (defaults to yourself)")
    async def score(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user
        user = await self.db.get_user(interaction.guild.id, target.id)
        rank = get_rank(user["score"])

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
        embed.set_author(name=await self.bot.format_user_full(target, interaction.guild.id), icon_url=target.display_avatar.url)
        embed.add_field(name="SCORE", value=f"{user['score']:.2f}", inline=True)
        embed.add_field(name="RANK", value=rank["name"], inline=True)
        await interaction.followup.send(embed=embed)

    @commands.command(name="yuan")
    async def yuan_prefix(self, ctx, citizen: discord.Member = None):
        async with ctx.typing():
            target = citizen or ctx.author
            user = await self.db.get_user(ctx.guild.id, target.id)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.set_author(name=await self.bot.format_user_full(target, ctx.guild.id), icon_url=target.display_avatar.url)
            embed.add_field(name="BALANCE", value=f"¥{user['yuan']}", inline=True)
            embed.add_field(name="TOTAL EARNED", value=f"¥{user['total_yuan_earned']}", inline=True)
            embed.add_field(name="TOTAL SPENT", value=f"¥{user['total_yuan_spent']}", inline=True)
        await ctx.send(embed=embed)

    @commands.command(name="stats")
    async def stats_prefix(self, ctx, citizen: discord.Member = None):
        async with ctx.typing():
            target = citizen or ctx.author
            gid = ctx.guild.id
            user = await self.db.get_user(gid, target.id)
            rank = get_rank(user["score"])
            trend_7d  = await self.db.get_score_trend(gid, target.id, 7)
            trend_30d = await self.db.get_score_trend(gid, target.id, 30)

            def trend_str(val):
                if val > 0: return f"▲ +{val:.2f}"
                if val < 0: return f"▼ {val:.2f}"
                return "= 0.00"

            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公民档案")
            embed.set_author(name=await self.bot.format_user_full(target, gid), icon_url=target.display_avatar.url)
            embed.add_field(name="SCORE",     value=f"{user['score']:.2f}", inline=True)
            embed.add_field(name="RANK",      value=rank["name"],            inline=True)
            embed.add_field(name="YUAN",      value=f"¥{user['yuan']}",     inline=True)
            embed.add_field(name="7D TREND",  value=trend_str(trend_7d),    inline=True)
            embed.add_field(name="30D TREND", value=trend_str(trend_30d),   inline=True)
            embed.add_field(name="MESSAGES",  value=str(user["message_count"]), inline=True)
            embed.add_field(name="PEAK",      value=f"{user['highest_score']:.2f}", inline=True)
            embed.add_field(name="LOW",       value=f"{user['lowest_score']:.2f}",  inline=True)
            embed.add_field(name="ITEMS BOUGHT", value=str(user["items_bought"]), inline=True)
            embed.timestamp = discord.utils.utcnow()
        await ctx.send(embed=embed)

    @commands.command(name="score")
    async def score_prefix(self, ctx, citizen: discord.Member = None):
        async with ctx.typing():
            target = citizen or ctx.author
            user = await self.db.get_user(ctx.guild.id, target.id)
            rank = get_rank(user["score"])
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.set_author(name=await self.bot.format_user_full(target, ctx.guild.id), icon_url=target.display_avatar.url)
            embed.add_field(name="SCORE", value=f"{user['score']:.2f}", inline=True)
            embed.add_field(name="RANK", value=rank["name"], inline=True)
        await ctx.send(embed=embed)

    @app_commands.command(name="leaderboard", description="View the social credit rankings")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await self.db.get_extended_leaderboard(interaction.guild.id)

        def name(uid):
            m = interaction.guild.get_member(uid)
            return m.display_name if m else "Unknown"

        def fmt_score(rows):
            return "\n".join(f"{i}. {name(r['user_id'])} · {r['score']:.2f}" for i, r in enumerate(rows, 1)) or "No data."

        def fmt_yuan(rows):
            return "\n".join(f"{i}. {name(r['user_id'])} · ¥{r['yuan']}" for i, r in enumerate(rows, 1)) or "No data."

        def fmt_col(rows, col):
            return "\n".join(f"{i}. {name(r['user_id'])} · {r[col]}" for i, r in enumerate(rows, 1)) or "No data."

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 排行榜")
        embed.add_field(name="MOST COMPLIANT", value=fmt_score(data["top_score"]), inline=True)
        embed.add_field(name="GREATEST THREATS", value=fmt_score(data["bottom_score"]), inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="WEALTHIEST", value=fmt_yuan(data["richest"]), inline=True)
        embed.add_field(name="POOREST", value=fmt_yuan(data["poorest"]), inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="MOST ACTIVE", value=fmt_col(data["most_messages"], "message_count"), inline=True)
        embed.add_field(name="MOST ENDORSED", value=fmt_col(data["most_endorsed"], "times_endorsed"), inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.add_field(name="MOST REBUKED", value=fmt_col(data["most_rebuked"], "times_rebuked"), inline=True)
        embed.add_field(name="TOP INFORMANTS", value=fmt_col(data["top_snitches"], "times_filed_reports"), inline=True)
        embed.add_field(name="​", value="​", inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="history", description="View score change history")
    @app_commands.describe(citizen="Citizen to look up (mod-only for others)")
    async def history(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer(ephemeral=True)
        target = citizen or interaction.user

        if target.id != interaction.user.id and not interaction.user.guild_permissions.manage_guild:
            await interaction.followup.send(
                "Insufficient clearance to view another citizen's record.", ephemeral=True
            )
            return

        rows = await self.db.get_score_history(interaction.guild.id, target.id, limit=5)
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 档案记录")
        embed.add_field(name="CITIZEN", value=await self.bot.format_user_full(target, interaction.guild.id), inline=False)

        if not rows:
            embed.add_field(name="RECORD", value="No entries on file.", inline=False)
        else:
            lines = []
            for row in rows:
                arrow = "▲" if row["delta"] > 0 else "▼"
                lines.append(f"{arrow} {abs(row['delta']):.2f} · {row['reason']} · <t:{row['timestamp']}:R>")
            embed.add_field(name="RECENT ENTRIES", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="stats", description="View detailed statistics for a citizen")
    @app_commands.describe(citizen="Citizen to look up (defaults to yourself)")
    async def stats(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user
        gid = interaction.guild.id
        user = await self.db.get_user(gid, target.id)
        rank = get_rank(user["score"])

        trend_7d  = await self.db.get_score_trend(gid, target.id, 7)
        trend_30d = await self.db.get_score_trend(gid, target.id, 30)

        def trend_str(val: float) -> str:
            if val > 0:
                return f"▲ +{val:.2f}"
            elif val < 0:
                return f"▼ {val:.2f}"
            return "= 0.00"

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公民档案")
        embed.set_author(name=await self.bot.format_user_full(target, gid), icon_url=target.display_avatar.url)

        embed.add_field(name="SCORE",  value=f"{user['score']:.2f}", inline=True)
        embed.add_field(name="RANK",   value=rank["name"],            inline=True)
        embed.add_field(name="YUAN",   value=f"¥{user['yuan']}",      inline=True)

        embed.add_field(name="7D TREND",  value=trend_str(trend_7d),  inline=True)
        embed.add_field(name="30D TREND", value=trend_str(trend_30d), inline=True)
        embed.add_field(name="​", value="​", inline=True)

        embed.add_field(name="PEAK",     value=f"{user['highest_score']:.2f}",  inline=True)
        embed.add_field(name="LOW",      value=f"{user['lowest_score']:.2f}",   inline=True)
        embed.add_field(name="MESSAGES", value=str(user["message_count"]),       inline=True)

        embed.add_field(name="​", value="​", inline=False)

        embed.add_field(name="ENDORSED (recv)",  value=str(user["times_endorsed"]),     inline=True)
        embed.add_field(name="REBUKED (recv)",   value=str(user["times_rebuked"]),      inline=True)
        embed.add_field(name="​",          value="​",                        inline=True)

        embed.add_field(name="ENDORSED (given)", value=str(user["endorsements_given"]), inline=True)
        embed.add_field(name="REBUKED (given)",  value=str(user["rebukes_given"]),      inline=True)
        embed.add_field(name="​",          value="​",                        inline=True)

        embed.add_field(name="REPORTS RECEIVED", value=str(user["times_reported"]),      inline=True)
        embed.add_field(name="REPORTS FILED",    value=str(user["times_filed_reports"]), inline=True)
        embed.add_field(name="​",          value="​",                        inline=True)

        embed.add_field(name="​", value="​", inline=False)

        embed.add_field(name="YUAN EARNED",  value=f"¥{user['total_yuan_earned']}", inline=True)
        embed.add_field(name="YUAN SPENT",   value=f"¥{user['total_yuan_spent']}",  inline=True)
        embed.add_field(name="ITEMS BOUGHT", value=str(user["items_bought"]),        inline=True)

        streak = user.get("checkin_streak", 0)
        wins   = user.get("propaganda_wins", 0)
        if streak or wins:
            embed.add_field(name="​", value="​", inline=False)
        if streak:
            embed.add_field(name="CHECK-IN STREAK", value=f"{streak} days", inline=True)
        if wins:
            embed.add_field(name="PROPAGANDA VICTORIES", value=str(wins), inline=True)

        embed.timestamp = discord.utils.utcnow()
        embed.set_thumbnail(url="attachment://ccpstats.png")
        file = discord.File("images/ccpstats.png", filename="ccpstats.png")
        await interaction.followup.send(embed=embed, file=file)

    @app_commands.command(name="state_report", description="View the official state report for this server")
    async def state_report(self, interaction: discord.Interaction):
        await interaction.response.defer()
        data = await self.db.get_guild_stats(interaction.guild.id)
        if not data:
            await interaction.followup.send("Insufficient data for a state report.", ephemeral=True)
            return

        def member_name(user_id: int) -> str:
            m = interaction.guild.get_member(user_id)
            return m.display_name if m else "Unknown"

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 国家报告")

        embed.add_field(
            name="MOST COMPLIANT CITIZEN",
            value=f"{member_name(data['top_score']['user_id'])} · {data['top_score']['score']:.2f}",
            inline=False,
        )
        embed.add_field(
            name="GREATEST THREAT TO SOCIETY",
            value=f"{member_name(data['bottom_score']['user_id'])} · {data['bottom_score']['score']:.2f}",
            inline=False,
        )

        if data["biggest_rise"]:
            uid, val = data["biggest_rise"]
            embed.add_field(name="GREATEST RISE (7D)", value=f"{member_name(uid)} ▲ +{val:.2f}", inline=True)

        if data["biggest_fall"]:
            uid, val = data["biggest_fall"]
            embed.add_field(name="GREATEST FALL (7D)", value=f"{member_name(uid)} ▼ {val:.2f}", inline=True)

        if data["biggest_rise"] or data["biggest_fall"]:
            embed.add_field(name="​", value="​", inline=True)

        embed.add_field(
            name="MOST ACTIVE INFORMANT",
            value=f"{member_name(data['top_snitch']['user_id'])} · {data['top_snitch']['times_filed_reports']} reports",
            inline=False,
        )
        embed.add_field(name="TOTAL REPORTS",       value=str(data["total_reports"]),    inline=True)
        embed.add_field(name="YUAN IN CIRCULATION", value=f"¥{data['total_yuan']}",      inline=True)
        embed.add_field(name="AVERAGE SCORE",       value=f"{data['avg_score']:.2f}",   inline=True)
        embed.add_field(name="ACTIVE CITIZENS",     value=str(data["active_count"]),     inline=True)
        embed.timestamp = discord.utils.utcnow()
        embed.set_thumbnail(url="attachment://ccpstats.png")
        file = discord.File("images/ccpstats.png", filename="ccpstats.png")
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
