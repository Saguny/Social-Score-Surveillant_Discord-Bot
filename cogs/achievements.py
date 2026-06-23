import asyncio
import time

import discord
from discord import app_commands
from discord.ext import commands

from config.achievements import ACHIEVEMENTS, get_achievement, achievements_by_category
from infra.redis_client import get_redis
from infra.redis_cache import cache_set_nx

_ANNOUNCE_DEBOUNCE_SECS = 2.0
_ANNOUNCE_SAFETY_TTL = 30


class AchievementsCog(commands.Cog, name="Achievements"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def grant(
        self,
        guild: discord.Guild,
        user: discord.abc.User,
        achievement_id: str,
        *,
        channel: discord.abc.Messageable | None = None,
        message: discord.Message | None = None,
    ) -> bool:
        data = get_achievement(achievement_id)
        if data is None or guild is None:
            return False
        newly = await self.db.unlock_achievement(user.id, achievement_id, guild.id)
        if not newly:
            return False
        if data["badge"]:
            await self.db.add_cosmetic_badge(user.id, data["badge"])
        await self._apply_rewards_everywhere(user, data)
        await self._queue_announce(guild, user, achievement_id, channel)
        if achievement_id != "completionist":
            await self._check_completionist(guild, user, channel)
        return True

    async def _check_completionist(self, guild: discord.Guild, user: discord.abc.User, channel):
        total = len(ACHIEVEMENTS) - 1
        if total <= 0:
            return
        unlocked_rows = await self.db.get_unlocked_achievements(user.id)
        unlocked_ids = {r["achievement_id"] for r in unlocked_rows}
        unlocked_ids.discard("completionist")
        if len(unlocked_ids) >= total:
            await self.grant(guild, user, "completionist", channel=channel)

    async def _apply_rewards_everywhere(self, user: discord.abc.User, data: dict):
        guild_ids = await self.db.get_user_guild_ids(user.id)
        await asyncio.gather(*(self._apply_rewards(gid, user.id, data) for gid in guild_ids))

    async def _apply_rewards(self, guild_id: int, user_id: int, data: dict):
        tasks = []
        if data["yuan_reward"]:
            tasks.append(self.db.adjust_yuan(guild_id, user_id, data["yuan_reward"]))
        if data["score_reward"]:
            tasks.append(self.db.update_score(guild_id, user_id, float(data["score_reward"]), f"achievement: {data['name']}"))
        if tasks:
            await asyncio.gather(*tasks)

    async def _queue_announce(self, guild: discord.Guild, user: discord.abc.User, achievement_id: str, channel):
        r = get_redis()
        key_ids = f"ach:ids:{guild.id}:{user.id}"
        key_channel = f"ach:channel:{guild.id}:{user.id}"
        key_ready = f"ach:ready:{guild.id}:{user.id}"
        await r.rpush(key_ids, achievement_id)
        await r.expire(key_ids, _ANNOUNCE_SAFETY_TTL)
        if channel is not None:
            await cache_set_nx(key_channel, str(channel.id), ex=_ANNOUNCE_SAFETY_TTL)
        ready_at = int(time.time()) + int(_ANNOUNCE_DEBOUNCE_SECS)
        await cache_set_nx(key_ready, str(ready_at), ex=_ANNOUNCE_SAFETY_TTL)

    # ── /achievements ────────────────────────────────────────────────────────

    @app_commands.command(name="achievements", description="View unlocked and locked achievements")
    @app_commands.describe(citizen="Citizen to look up (defaults to yourself)")
    async def achievements(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user
        gid = interaction.guild.id
        unlocked_rows = await self.db.get_unlocked_achievements(target.id)
        unlocked = {r["achievement_id"]: r["unlocked_at"] for r in unlocked_rows}
        grouped = achievements_by_category()
        categories = list(grouped.keys())
        author_name = await self.bot.format_user_full(target, gid)
        unlock_counts, total_citizens = await asyncio.gather(
            self.db.get_achievement_counts(), self.db.get_total_citizen_count()
        )

        def pct_line(aid: str) -> str:
            if total_citizens <= 0:
                return ""
            pct = (unlock_counts.get(aid, 0) / total_citizens) * 100
            return f"\n{pct:.1f}% of citizens have this achievement"

        def build_embed(category: str) -> discord.Embed:
            e = discord.Embed(
                title=f"中华人民共和国社会信用局 · Achievements · {category.upper()}",
                color=0xFFD700,
            )
            e.set_author(name=author_name, icon_url=target.display_avatar.url)
            e.set_thumbnail(url="attachment://achievement.png")
            for aid in grouped[category]:
                data = get_achievement(aid)
                if aid in unlocked:
                    ts = unlocked[aid]
                    e.add_field(
                        name=f"✅ {data['name']}",
                        value=f"{data['description']}\n<t:{ts}:R>{pct_line(aid)}",
                        inline=False,
                    )
                elif data["secret"]:
                    e.add_field(name="🔒 ?????", value="A secret the Party keeps.", inline=False)
                else:
                    e.add_field(
                        name="🔒 ?????",
                        value=f"{data['hint'] or 'Unknown.'}{pct_line(aid)}",
                        inline=False,
                    )
            unlocked_count = sum(1 for aid in grouped[category] if aid in unlocked)
            e.set_footer(text=f"{unlocked_count}/{len(grouped[category])} unlocked in this category")
            return e

        class CategoryView(discord.ui.View):
            def __init__(self_v, active: str):
                super().__init__(timeout=180)
                self_v.active = active
                self_v._refresh_buttons()

            def _refresh_buttons(self_v):
                self_v.clear_items()
                for cat in categories:
                    style = discord.ButtonStyle.primary if cat == self_v.active else discord.ButtonStyle.secondary
                    btn = discord.ui.Button(label=cat.upper(), style=style)
                    btn.callback = self_v._make_cb(cat)
                    self_v.add_item(btn)

            def _make_cb(self_v, cat: str):
                async def callback(itr: discord.Interaction):
                    self_v.active = cat
                    self_v._refresh_buttons()
                    await itr.response.edit_message(embed=build_embed(cat), view=self_v)
                return callback

        file = discord.File("images/achievement.png", filename="achievement.png")
        await interaction.followup.send(file=file, embed=build_embed(categories[0]), view=CategoryView(categories[0]))


def build_announce_embeds(ids: list[str], user: discord.abc.User) -> list[discord.Embed]:
    embeds = []
    for aid in ids:
        data = get_achievement(aid)
        if not data:
            continue
        parts = []
        if data["score_reward"]:
            parts.append(f"{data['score_reward']:.2f} credit score")
        if data["yuan_reward"]:
            parts.append(f"¥{data['yuan_reward']:,} Yuan")
        reward_text = f" rewarding them with {' and '.join(parts)}" if parts else ""
        embed = discord.Embed(
            title="Achievement Unlocked!",
            description=f"{user.mention} has unlocked the **{data['name']}** achievement{reward_text}.",
            color=0xFFD700,
        )
        embed.set_thumbnail(url="attachment://achievement.png")
        embed.set_footer(text="ccp achievementnotification [on|off] · ccp achievementchannel [#channel]")
        embeds.append(embed)
    return embeds


async def deliver_achievement_announcements(
    db,
    guild: discord.Guild,
    user: discord.abc.User,
    ids: list[str],
    fallback_channel_id: int | None = None,
):
    if not ids:
        return
    loud = await db.get_achievements_loud_enabled(guild.id)
    if not loud:
        return
    configured_channel_id = await db.get_achievements_channel(guild.id)
    channel_id = configured_channel_id or fallback_channel_id
    channel = guild.get_channel(channel_id) if channel_id else None
    if channel is None:
        return
    embeds = build_announce_embeds(ids, user)
    if not embeds:
        return
    file = discord.File("images/achievement.png", filename="achievement.png")
    try:
        await channel.send(file=file, embeds=embeds)
    except (discord.Forbidden, discord.HTTPException):
        pass


async def unlock(
    bot: commands.Bot,
    guild: discord.Guild,
    user: discord.abc.User,
    achievement_id: str,
    *,
    channel: discord.abc.Messageable | None = None,
    message: discord.Message | None = None,
) -> bool:
    cog = bot.get_cog("Achievements")
    if cog is None or guild is None:
        return False
    return await cog.grant(guild, user, achievement_id, channel=channel, message=message)


async def check_milestone(
    bot: commands.Bot,
    guild: discord.Guild,
    user: discord.abc.User,
    milestone_key: str,
    value: float,
    *,
    channel: discord.abc.Messageable | None = None,
) -> bool:
    if guild is None:
        return False
    unlocked_any = False
    for achievement_id, data in ACHIEVEMENTS.items():
        threshold = data.get("threshold")
        if data.get("milestone_key") != milestone_key or threshold is None:
            continue
        if value >= threshold:
            if await unlock(bot, guild, user, achievement_id, channel=channel):
                unlocked_any = True
    return unlocked_any


async def setup(bot: commands.Bot):
    await bot.add_cog(AchievementsCog(bot))
