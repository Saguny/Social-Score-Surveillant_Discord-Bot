import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config.achievements import ACHIEVEMENTS, get_achievement, achievements_by_category

_ANNOUNCE_DEBOUNCE_SECS = 2.0


class AchievementsCog(commands.Cog, name="Achievements"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._pending_ids: dict[tuple[int, int], list[str]] = {}
        self._pending_channel: dict[tuple[int, int], discord.abc.Messageable | None] = {}
        self._pending_tasks: dict[tuple[int, int], asyncio.Task] = {}

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
        self._queue_announce(guild, user, achievement_id, channel)
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
        targets = [g for g in self.bot.guilds if g.get_member(user.id) is not None]
        await asyncio.gather(*(self._apply_rewards(g.id, user.id, data) for g in targets))

    async def _apply_rewards(self, guild_id: int, user_id: int, data: dict):
        tasks = []
        if data["yuan_reward"]:
            tasks.append(self.db.adjust_yuan(guild_id, user_id, data["yuan_reward"]))
        if data["score_reward"]:
            tasks.append(self.db.update_score(guild_id, user_id, float(data["score_reward"]), f"achievement: {data['name']}"))
        if tasks:
            await asyncio.gather(*tasks)

    def _queue_announce(self, guild: discord.Guild, user: discord.abc.User, achievement_id: str, channel):
        key = (guild.id, user.id)
        self._pending_ids.setdefault(key, []).append(achievement_id)
        self._pending_channel[key] = channel
        existing = self._pending_tasks.get(key)
        if existing and not existing.done():
            return
        self._pending_tasks[key] = asyncio.create_task(self._flush_announce(guild, user, key))

    async def _flush_announce(self, guild: discord.Guild, user: discord.abc.User, key: tuple[int, int]):
        await asyncio.sleep(_ANNOUNCE_DEBOUNCE_SECS)
        ids = self._pending_ids.pop(key, [])
        fallback_channel = self._pending_channel.pop(key, None)
        self._pending_tasks.pop(key, None)
        if not ids:
            return

        loud = await self.db.get_achievements_loud_enabled(guild.id)
        if not loud:
            return

        configured_channel_id = await self.db.get_achievements_channel(guild.id)
        channel = guild.get_channel(configured_channel_id) if configured_channel_id else fallback_channel
        if channel is None:
            return

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
        if not embeds:
            return
        file = discord.File("images/achievement.png", filename="achievement.png")
        try:
            await channel.send(file=file, embeds=embeds)
        except (discord.Forbidden, discord.HTTPException):
            pass

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
