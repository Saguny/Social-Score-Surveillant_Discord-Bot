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

_COLOR = 0xCC0000

_METRIC_EMOJIS = {
    "happiness":    "☆",
    "gdp":          "¥",
    "civic":        "✉",
    "literacy":     "★",
    "incarceration": "⚠",
    "politburo":    "⬆",
}


def _fmt_metric(metric: str, value: float | None) -> str:
    if value is None:
        return "—"
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
            app_commands.Choice(name=_BRACKET_ALL, value=_BRACKET_ALL),
            *[app_commands.Choice(name=b, value=b) for b in _BRACKET_NAMES],
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
            rows = await self.db.get_guild_leaderboard(tab, bracket_arg, limit=10)
            this_guild = await self.db.get_guild_rank(interaction.guild.id)

            title_bracket = f" · {bkt}" if bkt != _BRACKET_ALL else ""
            embed = discord.Embed(
                color=_COLOR,
                title=f"中华人民共和国社会信用局 · SERVER ALMANAC{title_bracket}",
            )
            embed.description = f"**{METRIC_LABELS[tab]}**"

            lines = []
            for i, row in enumerate(rows, 1):
                name = row["guild_name"] or "Unknown Server"
                val = _fmt_metric(tab, row.get("value"))
                citizens = row.get("citizens", 0)
                lines.append(f"`{i:>2}.` **{name}** · {val} · {citizens} citizens")

            embed.add_field(
                name=f"TOP SERVERS",
                value="\n".join(lines) if lines else "No opted-in servers yet.",
                inline=False,
            )

            if this_guild:
                this_val = this_guild.get(tab)
                this_bracket = this_guild.get("bracket") or "—"
                visible = this_guild.get("leaderboard_visible", False)
                standing_lines = [
                    f"Bracket: **{this_bracket}**",
                    f"{METRIC_LABELS[tab]}: **{_fmt_metric(tab, this_val)}**",
                ]
                if not visible:
                    standing_lines.append("*Hidden · use `/serverrank visibility on` to appear on this list*")
                embed.add_field(name="YOUR STANDING", value="\n".join(standing_lines), inline=False)

            embed.set_thumbnail(url="attachment://bureau.png")
            embed.set_footer(text="/serverrank me for your full profile · /serverrank visibility [on|off] · GLORY TO THE CCP!")
            return embed

        class ServerRankTopView(discord.ui.View):
            def __init__(self_, tab: str, bkt: str):
                super().__init__(timeout=60)
                self_.tab = tab
                self_.bkt = bkt
                for m in METRICS:
                    btn = discord.ui.Button(
                        label=METRIC_LABELS[m],
                        style=discord.ButtonStyle.primary if m == tab else discord.ButtonStyle.secondary,
                        custom_id=f"tab_{m}",
                        row=0,
                    )
                    btn.callback = self_.make_tab_callback(m)
                    self_.add_item(btn)
                bracket_select = discord.ui.Select(
                    placeholder=bkt,
                    options=[
                        discord.SelectOption(label=_BRACKET_ALL, value=_BRACKET_ALL, default=bkt == _BRACKET_ALL),
                        *[
                            discord.SelectOption(label=b, value=b, default=bkt == b)
                            for b in _BRACKET_NAMES
                        ],
                    ],
                    row=1,
                )
                bracket_select.callback = self_.make_bracket_callback()
                self_.add_item(bracket_select)

            def make_tab_callback(self_, m: str):
                async def callback(btn_interaction: discord.Interaction):
                    await btn_interaction.response.edit_message(
                        embed=await build_embed(m, self_.bkt),
                        view=ServerRankTopView(m, self_.bkt),
                        attachments=[discord.File("images/bureau.png", filename="bureau.png")],
                    )
                return callback

            def make_bracket_callback(self_):
                async def callback(select_interaction: discord.Interaction):
                    new_bkt = select_interaction.data["values"][0]
                    await select_interaction.response.edit_message(
                        embed=await build_embed(self_.tab, new_bkt),
                        view=ServerRankTopView(self_.tab, new_bkt),
                        attachments=[discord.File("images/bureau.png", filename="bureau.png")],
                    )
                return callback

            async def on_timeout(self_):
                for item in self_.children:
                    item.disabled = True

        await interaction.followup.send(
            embed=await build_embed(tab, bkt),
            view=ServerRankTopView(tab, bkt),
            file=discord.File("images/bureau.png", filename="bureau.png"),
        )

    @serverrank.command(name="me", description="View this server's full almanac profile and rankings (mod only)")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def serverrank_me(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild = interaction.guild
        data = await self.db.get_guild_rank(guild.id)

        if not data:
            await interaction.followup.send(
                "This server has no citizens yet. Members need to chat to become citizens.",
                ephemeral=True,
            )
            return

        citizens = data.get("citizens", 0)
        bracket = data.get("bracket") or f"Below minimum ({GUILD_RANK_MIN_CITIZENS} citizens required)"
        visible = data.get("leaderboard_visible", False)
        total = data.get("total_guilds", "?")

        embed = discord.Embed(
            color=_COLOR,
            title="中华人民共和国社会信用局 · SERVER PROFILE",
        )
        embed.set_author(name=guild.name, icon_url=guild.icon.url if guild.icon else None)
        embed.set_thumbnail(url="attachment://bureau.png")
        embed.add_field(name="BRACKET", value=bracket, inline=True)
        embed.add_field(name="CITIZENS", value=str(citizens), inline=True)
        embed.add_field(name="VISIBILITY", value="Public" if visible else "Hidden", inline=True)

        for metric in METRICS:
            val = data.get("politburo") if metric == "politburo" else data.get(metric)
            rank_val = data.get(f"rank_{metric}")

            label = METRIC_LABELS[metric]
            formatted = _fmt_metric(metric, val)
            rank_str = f" · Rank #{rank_val} of {total}" if rank_val else ""
            embed.add_field(name=label, value=f"{formatted}{rank_str}", inline=False)

        rival_above = data.get("rival_above_name")
        rival_gap = data.get("rival_above_gap")
        if rival_above and rival_gap is not None:
            embed.add_field(
                name="NEARBY RIVAL",
                value=f"Only {rival_gap:.2f} behind **{rival_above}** · pass them to move up",
                inline=False,
            )

        embed.set_footer(text="/serverrank visibility [on|off] · /state_report for today's activity · GLORY TO THE CCP!")
        await interaction.followup.send(embed=embed, file=discord.File("images/bureau.png", filename="bureau.png"), ephemeral=True)

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
        await self.db.set_leaderboard_visible(interaction.guild.id, visible)
        if visible:
            await self.db.set_guild_name(interaction.guild.id, interaction.guild.name)
        msg = (
            f"**{interaction.guild.name}** will now appear on `/serverrank top` and the web leaderboard."
            if visible else
            f"**{interaction.guild.name}** is now hidden from the public leaderboard."
        )
        await interaction.followup.send(msg, ephemeral=True)

    @serverrank.command(name="card", description="Render a shareable rank card for this server (mod only)")
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.describe(metric="Which almanac stat to feature on the card")
    @app_commands.choices(metric=[app_commands.Choice(name=METRIC_LABELS[m], value=m) for m in METRICS])
    async def serverrank_card(self, interaction: discord.Interaction, metric: app_commands.Choice[str] = None):
        await interaction.response.defer()
        guild = interaction.guild
        tab = metric.value if metric else "happiness"

        visible = await self.db.is_leaderboard_visible(guild.id)
        if not visible:
            await interaction.followup.send(
                "Enable visibility first with `/serverrank visibility on` — the card shows your server's real name, "
                "which requires opting in.",
                ephemeral=True,
            )
            return

        data = await self.db.get_guild_rank(guild.id)
        if not data:
            await interaction.followup.send("No citizens yet — members need to chat first.", ephemeral=True)
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

        # percentile within bracket (fix 3: use bracket-scoped total)
        total = data.get("total_guilds_in_bracket") or data.get("total_guilds") or 1
        top_pct = max(1.0, (rank_val or 1) / total * 100)

        # rivals
        rival_name = data.get("rival_above_name")
        rival_gap = data.get("rival_above_gap")
        rivals_line = ""
        if rival_name and rival_gap is not None:
            rivals_line = f"Only {rival_gap:.2f} behind {rival_name}"

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
                rank=rank_val if rank_val is not None else 1,
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
        rank_display = f"#{rank_val}" if rank_val else "unranked"
        caption = (
            f"**{guild.name}** · {METRIC_LABELS[tab]} · "
            f"**{bracket}** {rank_display} · TOP {top_pct:.0f}%"
        )
        await interaction.followup.send(caption, file=file)

    @serverrank_me.error
    @serverrank_visibility.error
    @serverrank_card.error
    async def _mod_only_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError):
        if isinstance(error, app_commands.MissingPermissions):
            await interaction.response.send_message("This command requires Manage Server permission.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(ServerRankCog(bot))
