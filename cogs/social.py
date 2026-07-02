import asyncio
import io
import time
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from cogs.achievements import unlock as unlock_achievement, check_milestone
from config.ranks import get_rank

COOLDOWN_SECONDS = 86400
ENDORSE_DELTA = 1.5
REBUKE_DELTA = -1.5


class Social(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def _rate(
        self,
        interaction: discord.Interaction,
        target: discord.Member,
        etype: str,
        reason: str | None = None,
    ):
        gid = interaction.guild.id
        uid = interaction.user.id

        if target.bot or target.id == uid:
            embed = discord.Embed(color=0x888888, title="REQUEST DENIED", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value="The Bureau does not permit citizens to file ratings against themselves or automated accounts.", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)
            return

        await interaction.response.defer()

        existing = await self.db.get_endorsement(gid, uid, target.id)
        if existing and (int(time.time()) - existing["timestamp"]) < COOLDOWN_SECONDS:
            remaining = COOLDOWN_SECONDS - (int(time.time()) - existing["timestamp"])
            hours, mins = divmod(remaining // 60, 60)
            embed = discord.Embed(color=0x888888, title="ACTION UNAVAILABLE", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value=f"This citizen has already been rated. Bureau records indicate {hours}h {mins}m must pass before re-evaluation.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return

        await self.db.set_endorsement(gid, uid, target.id, etype)
        delta = ENDORSE_DELTA if etype == "endorse" else REBUKE_DELTA
        delta, _ = await self.db.apply_defense_chain(gid, target.id, delta)
        score_reason = f"citizen {etype}ment" + (f": {reason}" if reason else "")
        old_score, new_score = await self.db.update_score(gid, target.id, delta, score_reason)
        await self.db.update_social_counts(gid, target.id, uid, etype)

        if etype == "endorse":
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_endorsement", channel=interaction.channel)
            streak, _ = await self.db.bump_daily_streak(uid, "endorse_streak")
            await check_milestone(self.bot, interaction.guild, interaction.user, "endorse_streak", streak, channel=interaction.channel)
        else:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_rebuke", channel=interaction.channel)
            streak, _ = await self.db.bump_daily_streak(uid, "rebuke_streak")
            await check_milestone(self.bot, interaction.guild, interaction.user, "rebuke_streak", streak, channel=interaction.channel)
            if delta < 0:
                await self.db.record_negative_action(target.id)

        self.bot.dispatch("score_change", interaction.guild, target, interaction.channel, old_score, new_score)

        if etype == "endorse":
            embed = discord.Embed(color=0xFFD700, title="COMMENDATION FILED", description="中华人民共和国社会信用局")
            embed.set_author(name="The Bureau · Dept. of Citizen Affairs")
            embed.add_field(name="SUBJECT", value=target.mention, inline=True)
            embed.add_field(name="FILED BY", value=interaction.user.mention, inline=True)
            embed.add_field(name="RATING", value=f"{old_score:.2f} -> {new_score:.2f}  ({delta:+.2f})", inline=False)
        else:
            embed = discord.Embed(color=0xCC0000, title="CENSURE FILED", description="中华人民共和国社会信用局")
            embed.set_author(name="The Bureau · Dept. of Citizen Affairs")
            embed.add_field(name="SUBJECT", value=target.mention, inline=True)
            embed.add_field(name="FILED BY", value=interaction.user.mention, inline=True)
            embed.add_field(name="RATING", value=f"{old_score:.2f} -> {new_score:.2f}  ({delta:+.2f})", inline=False)

        if reason:
            embed.add_field(name="STATEMENT", value=reason[:200], inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="endorse", description="Commend a citizen's conduct (once per 24h per citizen)")
    @app_commands.describe(citizen="Citizen to commend", reason="Optional statement for the record")
    async def endorse(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "endorse", reason)

    @app_commands.command(name="rebuke", description="File a censure against a citizen (once per 24h per citizen)")
    @app_commands.describe(citizen="Citizen to censure", reason="Optional statement for the record")
    async def rebuke(self, interaction: discord.Interaction, citizen: discord.Member, reason: str = None):
        await self._rate(interaction, citizen, "rebuke", reason)

    @app_commands.command(name="compare", description="Request a Bureau loyalty comparison between two citizens")
    @app_commands.describe(
        citizen="First citizen to compare",
        against="Second citizen to compare (defaults to yourself)",
    )
    async def compare(self, interaction: discord.Interaction, citizen: discord.Member, against: discord.Member = None):
        a_user = citizen
        b_user = against or interaction.user

        if a_user.id == b_user.id:
            await interaction.response.send_message(
                "The Bureau does not permit citizens to compare themselves against themselves.", ephemeral=True
            )
            return

        await interaction.response.defer()

        gid = interaction.guild.id

        a_stats, b_stats = await asyncio.gather(
            self.db.get_compare_stats(gid, a_user.id),
            self.db.get_compare_stats(gid, b_user.id),
        )

        if not a_stats or not b_stats:
            await interaction.followup.send("One or both citizens have no Bureau record.", ephemeral=True)
            return

        _RANK_SHORT = {
            "Enemy of the State":   "Enemy",
            "Person of Interest":   "Person",
            "Unremarkable Citizen": "Unremark.",
            "Compliant Citizen":    "Compliant",
            "Model Citizen":        "Model",
            "Party Loyalist":       "Loyalist",
            "Cadre Member":         "Cadre",
            "General Secretary":    "Secretary",
        }
        a_rank_full = get_rank(a_stats["score"])["name"]
        b_rank_full = get_rank(b_stats["score"])["name"]
        a_rank = _RANK_SHORT.get(a_rank_full, a_rank_full)
        b_rank = _RANK_SHORT.get(b_rank_full, b_rank_full)

        W = 10
        L = 14
        TOTAL = 2 * W + L + 6  # 40

        def _trunc(s: str, w: int) -> str:
            return s if len(s) <= w else s[:w - 1] + "…"

        categories = [
            ("LOYALTY SCORE", f"{a_stats['score']:.2f}",       f"{b_stats['score']:.2f}",       a_stats["score"],          b_stats["score"]),
            ("RANK",          a_rank,                           b_rank,                           a_stats["score"],          b_stats["score"]),
            ("WEALTH",        f"¥{a_stats['yuan']:,}",          f"¥{b_stats['yuan']:,}",          a_stats["yuan"],           b_stats["yuan"]),
            ("CHECK-IN",      f"{a_stats['checkin_streak']}d",  f"{b_stats['checkin_streak']}d",  a_stats["checkin_streak"], b_stats["checkin_streak"]),
            ("MESSAGES",      f"{a_stats['message_count']:,}",  f"{b_stats['message_count']:,}",  a_stats["message_count"],  b_stats["message_count"]),
            ("COMMENDATIONS", str(a_stats["times_endorsed"]),   str(b_stats["times_endorsed"]),   a_stats["times_endorsed"], b_stats["times_endorsed"]),
            ("ACHIEVEMENTS",  str(a_stats["achievements"]),     str(b_stats["achievements"]),     a_stats["achievements"],   b_stats["achievements"]),
            ("PRESTIGE",      str(a_stats["prestige"]),         str(b_stats["prestige"]),         a_stats["prestige"],       b_stats["prestige"]),
        ]

        a_name = _trunc(a_user.display_name, W)
        b_name = _trunc(b_user.display_name, W)

        title_inner = " LOYALTY EVAL "
        side = (TOTAL - 2 - len(title_inner)) // 2
        top = "╔" + "═" * side + title_inner + "═" * (TOTAL - 2 - len(title_inner) - side) + "╗"
        sep = "─" * (W + 2) + "┼" + "─" * L + "┼" + "─" * (W + 2)

        lines = [
            top,
            f"{a_name:>{W}}  │{'CATEGORY':^{L}}│  {b_name:<{W}}",
            sep,
        ]

        a_wins = b_wins = 0
        for label, a_val, b_val, a_raw, b_raw in categories:
            a_disp = _trunc(str(a_val), W)
            b_disp = _trunc(str(b_val), W)
            if a_raw > b_raw:
                ind_a, ind_b = "◄", " "
                a_wins += 1
            elif b_raw > a_raw:
                ind_a, ind_b = " ", "►"
                b_wins += 1
            else:
                ind_a, ind_b = "·", "·"
            lines.append(f"{a_disp:>{W}} {ind_a}│{label:^{L}}│{ind_b} {b_disp:<{W}}")

        lines.append(sep)

        if a_wins > b_wins:
            gap = a_wins - b_wins
            verdict = f"{a_name} wins ({a_wins}-{b_wins})." if gap < 5 else f"{a_name} is an exemplary servant of the state."
        elif b_wins > a_wins:
            gap = b_wins - a_wins
            verdict = f"{b_name} wins ({b_wins}-{a_wins})." if gap < 5 else f"{b_name} is an exemplary servant of the state."
        else:
            verdict = "Equal loyalty to the state."

        prefix = "  VERDICT ► "
        lines.append(prefix + _trunc(verdict, TOTAL - len(prefix)))
        lines.append("╚" + "═" * (TOTAL - 2) + "╝")

        code_block = "```\n" + "\n".join(lines) + "\n```"

        async def _fetch_avatar(user: discord.Member) -> bytes:
            url = user.display_avatar.replace(size=128, format="png").url
            async with aiohttp.ClientSession() as session:
                async with session.get(url) as resp:
                    return await resp.read()

        a_av, b_av = await asyncio.gather(_fetch_avatar(a_user), _fetch_avatar(b_user))

        loop = asyncio.get_event_loop()
        from render.compare_card import render_compare_banner
        img_bytes = await loop.run_in_executor(None, render_compare_banner, a_av, b_av)

        file = discord.File(io.BytesIO(img_bytes), filename="compare.png")
        embed = discord.Embed(description=code_block, color=0xCC0000)
        embed.set_image(url="attachment://compare.png")
        await interaction.followup.send(embed=embed, file=file)


async def setup(bot: commands.Bot):
    await bot.add_cog(Social(bot))
