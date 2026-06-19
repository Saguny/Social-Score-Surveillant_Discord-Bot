import io
import datetime
import discord
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
from discord import app_commands
from discord.ext import commands
from config.ranks import get_rank, EXECUTION_THRESHOLD

STATS_THUMBNAIL = "attachment://ccpstats.png"


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

        pages = {
            "score":    ("MOST COMPLIANT",  fmt_score(data["top_score"]),                         "GREATEST THREATS", fmt_score(data["bottom_score"])),
            "economy":  ("WEALTHIEST",       fmt_yuan(data["richest"]),                            "POOREST",          fmt_yuan(data["poorest"])),
            "activity": ("MOST ACTIVE",      fmt_col(data["most_messages"], "message_count"),      "MOST ENDORSED",    fmt_col(data["most_endorsed"], "times_endorsed")),
            "social":   ("MOST REBUKED",     fmt_col(data["most_rebuked"], "times_rebuked"),       "TOP INFORMANTS",   fmt_col(data["top_snitches"], "times_filed_reports")),
        }

        def build_embed(page: str) -> discord.Embed:
            left_name, left_val, right_name, right_val = pages[page]
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 排行榜")
            embed.add_field(name=left_name,  value=left_val,  inline=True)
            embed.add_field(name=right_name, value=right_val, inline=True)
            embed.timestamp = discord.utils.utcnow()
            return embed

        labels = {"score": "SCORE", "economy": "ECONOMY", "activity": "ACTIVITY", "social": "SOCIAL"}

        class LeaderboardView(discord.ui.View):
            def __init__(self, current: str):
                super().__init__(timeout=60)
                self.current = current
                for page_id, label in labels.items():
                    btn = discord.ui.Button(
                        label=label,
                        style=discord.ButtonStyle.primary if page_id == current else discord.ButtonStyle.secondary,
                        custom_id=page_id,
                    )
                    btn.callback = self.make_callback(page_id)
                    self.add_item(btn)

            def make_callback(self, page_id: str):
                async def callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.edit_message(embed=build_embed(page_id), view=LeaderboardView(page_id))
                return callback

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True

        await interaction.followup.send(embed=build_embed("score"), view=LeaderboardView("score"))

    @app_commands.command(name="daily_report", description="View today's score and yuan activity for a citizen")
    @app_commands.describe(citizen="Citizen to look up (defaults to yourself)")
    async def daily_report(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user

        data = await self.db.get_daily_stats(interaction.guild.id, target.id)

        net_today     = round(data["pos_today"] + data["neg_today"], 2)
        net_yesterday = round(data["pos_yesterday"] + data["neg_yesterday"], 2)
        net_diff      = round(net_today - net_yesterday, 2)
        yuan_change   = data["yuan"] - data["prev_day_yuan"]

        if net_diff > 0:   net_vs = f"▲ +{net_diff:.2f} better than yesterday"
        elif net_diff < 0: net_vs = f"▼ {net_diff:.2f} worse than yesterday"
        else:              net_vs = "= same as yesterday"

        yuan_vs = ""
        if data["prev_day_yuan"] is not None:
            if yuan_change >= 0:
                yuan_vs = f"  ▲ +¥{yuan_change:,} vs yesterday"
            else:
                yuan_vs = f"  ▼ -¥{abs(yuan_change):,} vs yesterday"

        RESET = "[0m"
        GREEN = "[32m"
        RED   = "[31m"
        GRAY  = "[2;37m"

        ESC   = "\x1b"
        RESET = f"{ESC}[0m"
        GREEN = f"{ESC}[32m"
        RED   = f"{ESC}[31m"
        GRAY  = f"{ESC}[2;37m"

        net_color  = GREEN if net_today >= 0 else RED
        yuan_color = GREEN if yuan_change >= 0 else RED

        pos  = f"+{data['pos_today']:.2f}"
        neg  = f"{data['neg_today']:.2f}"
        net  = f"{net_today:+.2f}"
        yuan = f"¥{data['yuan']:,}"
        table = (
            f"{GREEN}SCORE GAINED  {pos:>8}{RESET}\n"
            f"{RED}SCORE LOST    {neg:>8}{RESET}\n"
            f"{net_color}NET TODAY     {net:>8}{RESET}  {GRAY}{net_vs}{RESET}\n"
            f"\n"
            f"{yuan_color}YUAN          {yuan:>8}{RESET}{GRAY}{yuan_vs}{RESET}"
        )

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 日报告")
        embed.set_author(name=await self.bot.format_user_full(target, interaction.guild.id), icon_url=target.display_avatar.url)
        embed.add_field(name="", value=f"```ansi\n{table}\n```", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

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
            if val > 0: return f"▲ +{val:.2f}"
            if val < 0: return f"▼ {val:.2f}"
            return "= 0.00"

        streak = user.get("checkin_streak", 0)
        wins   = user.get("propaganda_wins", 0)
        author_name = await self.bot.format_user_full(target, gid)

        def build_overview(thumb_url: str | None) -> discord.Embed:
            e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公民档案")
            e.set_author(name=author_name, icon_url=target.display_avatar.url)
            e.add_field(name="SCORE",      value=f"{user['score']:.2f}",        inline=True)
            e.add_field(name="RANK",       value=rank["name"],                   inline=True)
            e.add_field(name="YUAN",       value=f"¥{user['yuan']}",             inline=True)
            e.add_field(name="7D TREND",   value=trend_str(trend_7d),            inline=True)
            e.add_field(name="30D TREND",  value=trend_str(trend_30d),           inline=True)
            e.add_field(name="MESSAGES",   value=str(user["message_count"]),     inline=True)
            e.add_field(name="PEAK",       value=f"{user['highest_score']:.2f}", inline=True)
            e.add_field(name="LOW",        value=f"{user['lowest_score']:.2f}",  inline=True)
            if thumb_url:
                e.set_thumbnail(url=thumb_url)
            e.timestamp = discord.utils.utcnow()
            return e

        def build_social(thumb_url: str | None) -> discord.Embed:
            e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公民档案")
            e.set_author(name=author_name, icon_url=target.display_avatar.url)
            e.add_field(name="ENDORSED (recv)",  value=str(user["times_endorsed"]),      inline=True)
            e.add_field(name="ENDORSED (given)", value=str(user["endorsements_given"]),  inline=True)
            e.add_field(name="REBUKED (recv)",   value=str(user["times_rebuked"]),       inline=True)
            e.add_field(name="REBUKED (given)",  value=str(user["rebukes_given"]),       inline=True)
            e.add_field(name="REPORTS RECEIVED", value=str(user["times_reported"]),      inline=True)
            e.add_field(name="REPORTS FILED",    value=str(user["times_filed_reports"]), inline=True)
            if thumb_url:
                e.set_thumbnail(url=thumb_url)
            e.timestamp = discord.utils.utcnow()
            return e

        def build_economy(thumb_url: str | None) -> discord.Embed:
            e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公民档案")
            e.set_author(name=author_name, icon_url=target.display_avatar.url)
            e.add_field(name="YUAN EARNED",  value=f"¥{user['total_yuan_earned']}", inline=True)
            e.add_field(name="YUAN SPENT",   value=f"¥{user['total_yuan_spent']}",  inline=True)
            e.add_field(name="ITEMS BOUGHT", value=str(user["items_bought"]),        inline=True)
            if streak:
                e.add_field(name="CHECK-IN STREAK",      value=f"{streak} days", inline=True)
            if wins:
                e.add_field(name="PROPAGANDA VICTORIES", value=str(wins),         inline=True)
            if thumb_url:
                e.set_thumbnail(url=thumb_url)
            e.timestamp = discord.utils.utcnow()
            return e

        builders = {"overview": build_overview, "social": build_social, "economy": build_economy}
        labels   = {"overview": "OVERVIEW", "social": "SOCIAL", "economy": "ECONOMY"}

        class StatsView(discord.ui.View):
            def __init__(self, current: str, thumb_url: str | None):
                super().__init__(timeout=60)
                self.thumb_url = thumb_url
                for page_id, label in labels.items():
                    btn = discord.ui.Button(
                        label=label,
                        style=discord.ButtonStyle.primary if page_id == current else discord.ButtonStyle.secondary,
                        custom_id=page_id,
                    )
                    btn.callback = self.make_callback(page_id)
                    self.add_item(btn)

            def make_callback(self, page_id: str):
                async def callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.edit_message(
                        embed=builders[page_id](self.thumb_url),
                        view=StatsView(page_id, self.thumb_url),
                    )
                return callback

            async def on_timeout(self):
                for item in self.children:
                    item.disabled = True

        file = discord.File("images/ccpstats.png", filename="ccpstats.png")
        await interaction.followup.send(embed=build_overview(STATS_THUMBNAIL), view=StatsView("overview", STATS_THUMBNAIL), file=file)

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
        embed.set_thumbnail(url=STATS_THUMBNAIL)
        embed.timestamp = discord.utils.utcnow()
        file = discord.File("images/ccpstats.png", filename="ccpstats.png")
        await interaction.followup.send(embed=embed, file=file)


    @app_commands.command(name="graph", description="View a 30-day trend graph for score or yuan")
    @app_commands.describe(type="What to graph", citizen="Citizen to look up (defaults to yourself)")
    @app_commands.choices(type=[
        app_commands.Choice(name="Score", value="score"),
        app_commands.Choice(name="Yuan",  value="yuan"),
    ])
    async def graph(self, interaction: discord.Interaction, type: app_commands.Choice[str], citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user
        gid, uid = interaction.guild.id, target.id

        buf = await _build_graph(self.db, gid, uid, type.value, str(target.display_name))
        if buf is None:
            await interaction.followup.send("Not enough data yet to build a graph.", ephemeral=True)
            return

        label = type.name
        file = discord.File(buf, filename="graph.png")
        embed = discord.Embed(color=0xCC0000, title=f"中华人民共和国社会信用局 · 30-DAY {label.upper()} TREND")
        embed.set_author(name=await self.bot.format_user_full(target, gid), icon_url=target.display_avatar.url)
        embed.set_image(url="attachment://graph.png")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, file=file)


async def _build_graph(db, guild_id: int, user_id: int, graph_type: str, display_name: str):
    now = datetime.datetime.now(datetime.timezone.utc)
    days_back = 30

    if graph_type == "score":
        data = await db.get_score_graph_data(guild_id, user_id, days=days_back)
        rows = data["rows"]
        current = data["current_score"]

        daily = {r["day"]: float(r["net_delta"]) for r in rows}
        total_delta = sum(daily.values())
        base = current - total_delta

        day_seconds = [
            int((now - datetime.timedelta(days=days_back - i)).replace(hour=0, minute=0, second=0, microsecond=0).timestamp())
            for i in range(days_back + 1)
        ]
        scores = []
        running = base
        for ts in day_seconds:
            running += daily.get(ts, 0.0)
            scores.append(round(running, 2))

        dates = [datetime.datetime.fromtimestamp(ts, tz=datetime.timezone.utc) for ts in day_seconds]
        values = scores
        ylabel = "Score"
        line_color = "#CC0000"
        fill_color = "#CC000033"
        ref_lines = [
            (750.0,  "#888888", "--", "Neutral (750)"),
            (EXECUTION_THRESHOLD, "#8B0000", ":", f"Execution ({EXECUTION_THRESHOLD})"),
        ]

    else:
        rows = await db.get_yuan_graph_data(guild_id, user_id, days=days_back)
        if not rows:
            return None
        dates  = [datetime.datetime.fromtimestamp(r["day"], tz=datetime.timezone.utc) for r in rows]
        values = [r["yuan"] for r in rows]
        ylabel = "Yuan (¥)"
        line_color = "#FFD700"
        fill_color = "#FFD70033"
        ref_lines = []

    if len(dates) < 2:
        return None

    fig, ax = plt.subplots(figsize=(10, 4))
    fig.patch.set_facecolor("#1a1a2e")
    ax.set_facecolor("#1a1a2e")

    ax.plot(dates, values, color=line_color, linewidth=2, zorder=3)
    ax.fill_between(dates, values, min(values), color=fill_color, zorder=2)

    for y_val, color, style, label in ref_lines:
        ax.axhline(y=y_val, color=color, linestyle=style, linewidth=1, alpha=0.6, label=label)

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(mdates.WeekdayLocator(interval=1))
    fig.autofmt_xdate()

    ax.set_ylabel(ylabel, color="#aaaaaa", fontsize=9)
    ax.tick_params(colors="#aaaaaa", labelsize=8)
    for spine in ax.spines.values():
        spine.set_edgecolor("#333355")
    ax.grid(axis="y", color="#333355", linewidth=0.5, zorder=1)

    if ref_lines:
        legend = ax.legend(fontsize=7, facecolor="#1a1a2e", edgecolor="#333355", labelcolor="#aaaaaa")

    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=120, facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf


async def setup(bot: commands.Bot):
    await bot.add_cog(Stats(bot))
