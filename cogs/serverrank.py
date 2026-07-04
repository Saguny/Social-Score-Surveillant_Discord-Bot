import asyncio
import io
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from database._guilds import METRICS, METRIC_LABELS, _bracket_for
from config.rules import GUILD_RANK_BRACKETS, GUILD_RANK_MIN_CITIZENS
from render.serverrank_card import render_card


_BRACKET_NAMES = [b[0] for b in GUILD_RANK_BRACKETS]
_BRACKET_ALL = "All"

_BRACKET_PLURALS = {
    "Hamlet":     "Hamlets",
    "Village":    "Villages",
    "Town":       "Towns",
    "City":       "Cities",
    "Metropolis": "Metropolises",
}

_RANK_MEDALS = {1: "🥇 ", 2: "🥈 ", 3: "🥉 "}


def _rank_medal(rank: int) -> str:
    return _RANK_MEDALS.get(rank, "")


def _bracket_plural(bracket: str) -> str:
    return _BRACKET_PLURALS.get(bracket, f"{bracket}s")

_COLOR = 0xCC0000

_METRIC_EMOJIS = {
    "happiness":    "☆",
    "gdp":          "¥",
    "civic":        "✉",
    "literacy":     "★",
    "incarceration": "⚠",
    "politburo":    "⬆",
}

_METRIC_DESCRIPTIONS = {
    "happiness":     "Average social credit score across all citizens",
    "gdp":           "Total yuan held per citizen - higher means a wealthier server",
    "civic":         "Messages sent per active citizen - measures how engaged your community is",
    "literacy":      "Share of citizens who have unlocked at least one achievement",
    "incarceration": "Share of citizens currently on the execution list - lower is better",
    "politburo":     "Average score of the top 10 citizens - the strength of your server's elite",
}


def _fmt_metric(metric: str, value: float | None) -> str:
    if value is None:
        return "-"
    if metric == "happiness":
        return f"{value:.2f}"
    if metric == "gdp":
        return f"¥{value:,.0f}"
    if metric == "civic":
        return f"{value:.1f} msg/citizen"
    if metric in ("literacy", "incarceration"):
        return f"{value * 100:.1f}%"
    if metric == "politburo":
        return f"{value:.2f}"
    return f"{value:.2f}"


def _lower_is_better(metric: str) -> bool:
    return metric == "incarceration"


class ServerRankCog(commands.Cog, name="ServerRank"):
    def __init__(self, bot):
        self.bot = bot

    @property
    def db(self):
        return self.bot.db

    serverrank = app_commands.Group(name="serverrank", description="Server-vs-server social credit rankings")

    @serverrank.command(name="top", description="Browse the server leaderboard by metric and bracket")
    @app_commands.describe(
        metric="Which almanac stat to rank by",
        bracket="Size bracket to filter (omit for all brackets)",
    )
    @app_commands.choices(
        metric=[app_commands.Choice(name=METRIC_LABELS[m], value=m) for m in METRICS],
        bracket=[
            app_commands.Choice(name=_BRACKET_ALL,            value=_BRACKET_ALL),
            app_commands.Choice(name="Hamlet (10–24)",        value="Hamlet"),
            app_commands.Choice(name="Village (25–49)",       value="Village"),
            app_commands.Choice(name="Town (50–99)",          value="Town"),
            app_commands.Choice(name="City (100–249)",        value="City"),
            app_commands.Choice(name="Metropolis (250+)",     value="Metropolis"),
        ],
    )
    async def serverrank_top(
        self,
        interaction: discord.Interaction,
        metric: app_commands.Choice[str] = None,
        bracket: app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        tab = metric.value if metric else "happiness"
        bkt = (bracket.value if bracket else _BRACKET_ALL)

        async def build_embed(tab: str, bkt: str) -> discord.Embed:
            bracket_arg = None if bkt == _BRACKET_ALL else bkt
            rows, this_guild, visible, visible_ids = await asyncio.gather(
                self.db.get_guild_leaderboard(tab, bracket_arg, limit=10),
                self.db.get_guild_rank(interaction.guild.id),
                self.db.is_leaderboard_visible(interaction.guild.id),
                self.db.get_visible_guild_ids(),
            )

            title_bracket = f" · {bkt}" if bkt != _BRACKET_ALL else ""
            embed = discord.Embed(
                color=_COLOR,
                title=f"中华人民共和国社会信用局 · SERVER ALMANAC{title_bracket}",
            )
            embed.description = f"**{METRIC_LABELS[tab]}**"

            lines = []
            for i, row in enumerate(rows, 1):
                gid = row.get("guild_id")
                if gid in visible_ids or gid == interaction.guild.id:
                    g = self.bot.get_guild(gid)
                    name = g.name if g else "Private Server"
                else:
                    name = "Private Server"
                val = _fmt_metric(tab, row.get("value"))
                citizens = row.get("citizens", 0)
                lines.append(f"`{i:>2}.` **{name}** · {val} · {citizens} citizens")

            embed.add_field(
                name="TOP SERVERS",
                value="\n".join(lines) if lines else "No servers ranked yet.",
                inline=False,
            )

            if this_guild:
                this_val = this_guild.get(tab)
                this_bracket = this_guild.get("bracket") or "-"
                rank_val = this_guild.get(f"rank_{tab}")
                total_guilds = this_guild.get("total_guilds") or "?"
                rank_str = f"#{rank_val} of {total_guilds}" if rank_val else "unranked"
                top_pct = 1.0 if rank_val == 1 else max(1.0, (rank_val / total_guilds * 100)) if isinstance(rank_val, int) and isinstance(total_guilds, int) else None
                pct_str = f" · TOP {top_pct:.0f}%" if top_pct is not None else ""
                if bkt != _BRACKET_ALL and this_bracket != bkt:
                    embed.add_field(
                        name="YOUR STANDING",
                        value=f"Your server is in the **{this_bracket}** bracket · select that bracket to see your standing",
                        inline=False,
                    )
                else:
                    standing_lines = [
                        f"Bracket: **{this_bracket}**",
                        f"Rank: **{rank_str}{pct_str}**",
                        f"{METRIC_LABELS[tab]}: **{_fmt_metric(tab, this_val)}**",
                    ]
                    if not visible:
                        standing_lines.append("*Hidden · use `/serverrank visibility on` to appear on this list*")
                    embed.add_field(name="YOUR STANDING", value="\n".join(standing_lines), inline=False)

            embed.set_thumbnail(url="attachment://security.png")
            embed.set_footer(text=f"{_METRIC_DESCRIPTIONS[tab]} · /serverrank me for your full profile · /serverrank visibility [on|off] · GLORY TO THE CCP!")
            return embed

        class ServerRankTopView(discord.ui.View):
            def __init__(self_, tab: str, bkt: str):
                super().__init__(timeout=60)
                self_.tab = tab
                self_.bkt = bkt
                for i, m in enumerate(METRICS):
                    btn = discord.ui.Button(
                        label=METRIC_LABELS[m],
                        style=discord.ButtonStyle.primary if m == tab else discord.ButtonStyle.secondary,
                        custom_id=f"tab_{m}",
                        row=0 if i < 3 else 1,
                    )
                    btn.callback = self_.make_tab_callback(m)
                    self_.add_item(btn)
                bracket_select = discord.ui.Select(
                    placeholder=bkt,
                    row=2,
                    options=[
                        discord.SelectOption(label=_BRACKET_ALL, value=_BRACKET_ALL, default=bkt == _BRACKET_ALL),
                        *[
                            discord.SelectOption(label=b, value=b, default=bkt == b)
                            for b in _BRACKET_NAMES
                        ],
                    ],
                )
                bracket_select.callback = self_.make_bracket_callback()
                self_.add_item(bracket_select)

            def make_tab_callback(self_, m: str):
                async def callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.edit_message(
                        embed=await build_embed(m, self_.bkt),
                        view=ServerRankTopView(m, self_.bkt),
                        attachments=[discord.File("images/security.png", filename="security.png")],
                    )
                return callback

            def make_bracket_callback(self_):
                async def callback(select_interaction: discord.Interaction):
                    new_bkt = select_interaction.data["values"][0]
                    await select_interaction.response.edit_message(
                        embed=await build_embed(self_.tab, new_bkt),
                        view=ServerRankTopView(self_.tab, new_bkt),
                        attachments=[discord.File("images/security.png", filename="security.png")],
                    )
                return callback

            async def on_timeout(self_):
                for item in self_.children:
                    item.disabled = True

        await interaction.followup.send(
            embed=await build_embed(tab, bkt),
            view=ServerRankTopView(tab, bkt),
            file=discord.File("images/security.png", filename="security.png"),
        )

    @serverrank.command(name="me", description="View this server's full almanac profile and rankings")
    async def serverrank_me(self, interaction: discord.Interaction):
        await interaction.response.defer()
        guild = interaction.guild
        data = await self.db.get_guild_rank(guild.id)

        if not data:
            await interaction.followup.send(
                "This server has no citizens yet. Members need to chat to become citizens.",
            )
            return

        citizens = data.get("citizens", 0)
        raw_bracket = data.get("bracket")
        bracket = raw_bracket or f"Below minimum ({GUILD_RANK_MIN_CITIZENS} citizens required)"
        visible = data.get("leaderboard_visible", False)
        total_in_bracket = data.get("total_guilds_in_bracket")

        embed = discord.Embed(
            color=_COLOR,
            title="中华人民共和国社会信用局 · SERVER PROFILE",
        )
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        embed.set_thumbnail(url="attachment://security.png")
        embed.add_field(name="BRACKET", value=bracket, inline=True)
        embed.add_field(name="CITIZENS", value=str(citizens), inline=True)
        embed.add_field(name="VISIBILITY", value="Public" if visible else "Hidden", inline=True)

        for metric in METRICS:
            val = data.get("politburo") if metric == "politburo" else data.get(metric)
            bracket_rank_val = data.get(f"bracket_rank_{metric}")

            label = METRIC_LABELS[metric]
            formatted = _fmt_metric(metric, val)
            if raw_bracket and bracket_rank_val and total_in_bracket:
                rank_line = (
                    f"\n{_rank_medal(bracket_rank_val)}#{bracket_rank_val} / "
                    f"{total_in_bracket} {_bracket_plural(raw_bracket)}"
                )
            else:
                rank_line = ""
            embed.add_field(name=label, value=f"{formatted}{rank_line}", inline=False)

        rival_above = data.get("rival_above_name")
        rival_gap = data.get("rival_above_gap")
        if rival_above and rival_gap is not None:
            embed.add_field(
                name="NEARBY RIVAL",
                value=f"Only **{rival_gap:.2f} happiness points** behind **{rival_above}** · pass them to move up",
                inline=False,
            )

        embed.set_footer(text="/serverrank visibility [on|off] · /state_report for today's activity · GLORY TO THE CCP!")
        await interaction.followup.send(embed=embed, file=discord.File("images/security.png", filename="security.png"))

    @serverrank.command(name="visibility", description="Show or hide this server on the public leaderboard (mod only)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(state="Whether this server appears on /serverrank top and the web leaderboard")
    @app_commands.choices(state=[
        app_commands.Choice(name="On (show server name)", value="on"),
        app_commands.Choice(name="Off (stay hidden)", value="off"),
    ])
    async def serverrank_visibility(self, interaction: discord.Interaction, state: app_commands.Choice[str]):
        await interaction.response.defer(ephemeral=True)
        visible = state.value == "on"
        gid = interaction.guild.id
        if visible:
            await self.db.set_guild_name(gid, interaction.guild.name)
        await self.db.set_leaderboard_visible(gid, visible)

        msg = (
            f"**{interaction.guild.name}** will now appear on `/serverrank top` and the web leaderboard."
            if visible else
            f"**{interaction.guild.name}** is now hidden from the public leaderboard."
        )
        await interaction.followup.send(msg, ephemeral=True)

    @serverrank.command(name="card", description="Render a shareable rank card for this server")
    @app_commands.describe(
        metric="Which almanac stat to feature on the card",
        scope="Rank within your size bracket (default) or against all servers globally",
    )
    @app_commands.choices(
        metric=[app_commands.Choice(name=METRIC_LABELS[m], value=m) for m in METRICS],
        scope=[
            app_commands.Choice(name="Bracket (your size tier)", value="bracket"),
            app_commands.Choice(name="Global (all servers)",     value="global"),
        ],
    )
    async def serverrank_card(
        self,
        interaction: discord.Interaction,
        metric: app_commands.Choice[str] = None,
        scope:  app_commands.Choice[str] = None,
    ):
        await interaction.response.defer()
        guild = interaction.guild
        tab        = metric.value if metric else "happiness"
        use_bracket = (scope.value if scope else "bracket") == "bracket"

        data = await self.db.get_guild_rank(guild.id)
        if not data:
            await interaction.followup.send("No citizens yet - members need to chat first.", ephemeral=True)
            return

        bracket = data.get("bracket")
        if not bracket:
            await interaction.followup.send(
                f"This server needs at least {GUILD_RANK_MIN_CITIZENS} citizens to generate a card.",
                ephemeral=True,
            )
            return

        # metric value and rank
        raw_val = data.get("politburo") if tab == "politburo" else data.get(tab)
        rank_val = data.get(f"rank_{tab}")  # rank_politburo now included

        metric_value_str = _fmt_metric(tab, raw_val)

        # trend from 7-day snapshot
        snap = await self.db.get_guild_daily_snapshot(guild.id, 7)
        trend_arrow = ""
        trend_delta_str = ""
        if snap and raw_val is not None:
            old_val: float | None = None
            if tab == "happiness":
                old_val = snap.get("avg_score")
            elif tab == "gdp":
                c = snap.get("citizens") or 0
                old_val = snap["total_yuan"] / c if c else None
            elif tab == "civic":
                c = snap.get("citizens") or 0
                old_val = snap["total_messages"] / c if c else None
            elif tab == "literacy":
                old_val = snap.get("literacy_rate")
            elif tab == "incarceration":
                old_val = snap.get("incarceration_rate")
            elif tab == "politburo":
                pb_snap = snap.get("politburo_score")
                old_val = float(pb_snap) if pb_snap else None
            if old_val is not None:
                delta = raw_val - old_val
                trend_arrow = "▲" if delta >= 0 else "▼"
                trend_delta_str = _fmt_metric(tab, abs(delta))

        # rank, percentile, and rival - bracket-scoped or global
        rivals_line = ""
        if use_bracket and bracket:
            bracket_rows = await self.db.get_guild_leaderboard(tab, bracket, limit=500)
            display_rank = 1
            my_value = raw_val
            for idx, r in enumerate(bracket_rows, 1):
                if r.get("guild_id") == guild.id:
                    display_rank = idx
                    break
            total = len(bracket_rows) or 1
            # rival is the server directly above in the bracket
            if display_rank > 1:
                above = bracket_rows[display_rank - 2]
                above_name = above.get("guild_name") or "Private Server"
                above_val = above.get("value")
                if above_val is not None and my_value is not None:
                    gap = abs(above_val - my_value)
                    rivals_line = f"Only {gap:.2f} {METRIC_LABELS[tab].lower()} pts behind {above_name}"
        else:
            display_rank = rank_val or 1
            total = data.get("total_guilds") or 1
            rival_name = data.get("rival_above_name")
            rival_gap = data.get("rival_above_gap")
            if rival_name and rival_gap is not None:
                rivals_line = f"Only {rival_gap:.2f} happiness pts behind {rival_name}"
        top_pct = 1.0 if display_rank == 1 else max(1.0, display_rank / total * 100)

        # fetch guild icon
        icon_bytes: bytes | None = None
        if guild.icon:
            try:
                async with aiohttp.ClientSession() as sess:
                    async with sess.get(str(guild.icon.url)) as resp:
                        if resp.status == 200:
                            icon_bytes = await resp.read()
            except Exception:
                pass

        date_str = time.strftime("%Y-%m-%d", time.gmtime())

        loop = asyncio.get_running_loop()
        png = await loop.run_in_executor(
            None, lambda: render_card(
                guild_name=guild.name,
                rank=display_rank,
                bracket=bracket,
                metric=tab,
                metric_label=METRIC_LABELS[tab],
                metric_value=metric_value_str,
                trend_arrow=trend_arrow,
                trend_delta=trend_delta_str,
                percentile=top_pct,
                rivals_line=rivals_line,
                icon_bytes=icon_bytes,
                date_str=date_str,
            )
        )

        file = discord.File(io.BytesIO(png), filename="serverrank_card.png")
        scope_label = f"{bracket} bracket" if use_bracket and bracket else "global"
        caption = (
            f"**{guild.name}** · {METRIC_LABELS[tab]} · "
            f"#{display_rank} {scope_label} · TOP {top_pct:.0f}%"
        )
        await interaction.followup.send(caption, file=file)

    @serverrank_visibility.error
    async def _mod_only_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("This command requires Manage Server permission.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerRankCog(bot))
