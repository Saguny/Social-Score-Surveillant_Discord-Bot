import asyncio
import concurrent.futures
import io
import json
import os
import random
import time
import aiohttp
import discord
from discord.ext import commands
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config.ranks import get_rank, get_rank_index, RANKS, EXECUTION_THRESHOLD, RANK_YUAN
from config.rules import (
    SPAM_MIN_LENGTH, SPAM_DELTA, CAPS_MIN_LENGTH, CAPS_THRESHOLD, CAPS_DELTA,
    SENTIMENT_SCALE, SENTIMENT_NEUTRAL_THRESHOLD, NEUTRAL_BONUS, BANNED_TOPIC_PENALTY, YUAN_PER_MESSAGE,
    DAILY_MSG_SCORE_CAP, DAILY_NET_DIMINISHING_THRESHOLD, DAILY_MSG_DIMINISHING_FACTOR,
    SUPPORT_GUILD_ID, SUPPORT_YUAN_MULTIPLIER,
    YUAN_DAILY_DIMINISHING_THRESHOLD, YUAN_DAILY_DIMINISHING_FACTOR,
)
from config.banned_topics import contains_banned_topic
from cogs.achievements import unlock as unlock_achievement, check_milestone
from config.shop import COSMETIC_META
from render.rank_card import render_rank_card
from infra.redis_cache import cache_get, cache_set, cache_delete, cache_incr

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_LANG_CACHE_TTL = 3600

_module_analyzer = SentimentIntensityAnalyzer()
_worker_analyzer: SentimentIntensityAnalyzer | None = None


def _init_worker():
    import os
    global _worker_analyzer
    _worker_analyzer = SentimentIntensityAnalyzer()
    print(f"[scoring] worker pid={os.getpid()} ready", flush=True)


def _run_in_worker(text: str) -> tuple[str, float]:
    from langdetect import detect, LangDetectException
    try:
        lang = detect(text)
    except LangDetectException:
        lang = "en"
    a = _worker_analyzer if _worker_analyzer is not None else _module_analyzer
    return lang, a.polarity_scores(text)["compound"]


def _vader_only(text: str) -> float:
    a = _worker_analyzer if _worker_analyzer is not None else _module_analyzer
    return a.polarity_scores(text)["compound"]


class Scoring(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._last_messages: dict[tuple, str] = {}
        self._session: aiohttp.ClientSession | None = None
        self._executor: concurrent.futures.ProcessPoolExecutor | None = None
        self._role_locks: dict[tuple[int, str], asyncio.Lock] = {}

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(4, max(2, os.cpu_count() or 2)),
            initializer=_init_worker,
        )
        from infra.redis_cache import cache_set
        await cache_set("gateway:sentiment_workers", str(self._executor._max_workers))

    async def cog_unload(self):
        if self._session:
            await self._session.close()
            self._session = None
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

    async def _translate_to_english(self, text: str) -> str:
        try:
            params = {"client": "gtx", "sl": "auto", "tl": "en", "dt": "t", "q": text}
            async with self._session.get(
                TRANSLATE_URL, params=params, timeout=aiohttp.ClientTimeout(total=3)
            ) as resp:
                data = await resp.json(content_type=None)
                return "".join(part[0] for part in data[0] if part[0])
        except Exception:
            return text

    def _should_skip(self, message: discord.Message) -> bool:
        content = message.content.lower().strip()
        if content.startswith("http") and " " not in content:
            return True
        if not content and (message.attachments or message.stickers):
            return True
        return False

    async def _apply_yuan_diminishing(self, guild_id: int, user_id: int, yuan_gain: int, exempt: bool) -> int:
        key = f"yuandaily:{guild_id}:{user_id}"
        now_ts = int(time.time())
        today_start = now_ts // 86400 * 86400
        seconds_to_midnight = 86400 - (now_ts % 86400)
        raw = await cache_get(key)
        if raw is None:
            count = 0
        else:
            data = json.loads(raw)
            count = data["count"] if data.get("day") == today_start else 0
        count += 1
        await cache_set(
            key,
            json.dumps({"day": today_start, "count": count}),
            ex=seconds_to_midnight,
        )
        if not exempt and count > YUAN_DAILY_DIMINISHING_THRESHOLD:
            yuan_gain = round(yuan_gain * YUAN_DAILY_DIMINISHING_FACTOR)
        return yuan_gain

    def _structural_score(self, message: discord.Message) -> tuple[float, list[str]]:
        content = message.content.lower().strip()
        total = 0.0
        reasons = []
        key = (message.guild.id, message.author.id)

        if len(content) >= SPAM_MIN_LENGTH and self._last_messages.get(key) == content:
            total += SPAM_DELTA
            reasons.append("repeated transmission")

        raw = message.content
        if len(raw) >= CAPS_MIN_LENGTH:
            letters = [c for c in raw if c.isalpha()]
            if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= CAPS_THRESHOLD:
                total += CAPS_DELTA
                reasons.append("disruptive formatting")

        self._last_messages[key] = content
        return total, reasons

    async def _sentiment_score(self, guild_id: int, user_id: int, text: str) -> tuple[float, str | None]:
        if len(text.strip()) < 4:
            return 0.0, None

        loop = asyncio.get_event_loop()
        lang_key = f"lang:{guild_id}:{user_id}"
        cached_lang = await cache_get(lang_key)

        if cached_lang:
            lang = cached_lang
            english = text if lang == "en" else await self._translate_to_english(text)
            if contains_banned_topic(english):
                return BANNED_TOPIC_PENALTY, "counter-revolutionary speech"
            compound = await loop.run_in_executor(self._executor, _vader_only, english)
        else:
            lang, compound = await loop.run_in_executor(self._executor, _run_in_worker, text)
            await cache_set(lang_key, lang, ex=_LANG_CACHE_TTL)
            english = text if lang == "en" else await self._translate_to_english(text)
            if contains_banned_topic(english):
                return BANNED_TOPIC_PENALTY, "counter-revolutionary speech"
            if lang != "en":
                compound = await loop.run_in_executor(self._executor, _vader_only, english)

        streak_key = f"posstreak:{guild_id}:{user_id}"
        if abs(compound) < SENTIMENT_NEUTRAL_THRESHOLD:
            await cache_delete(streak_key)
            return NEUTRAL_BONUS, "civic participation"

        delta = round(compound * SENTIMENT_SCALE, 2)
        if delta > 0:
            streak = await cache_incr(streak_key)
            if streak >= 3:
                multiplier = 1.0 + min(streak // 3, 5) * 0.1
                delta = round(delta * multiplier, 2)
        else:
            await cache_delete(streak_key)
        return delta, "positive sentiment" if compound > 0 else "negative sentiment"

    async def _evaluate(self, message: discord.Message, struct_delta: float, reasons: list[str]) -> tuple[float, str]:
        sent_delta, sent_reason = await self._sentiment_score(
            message.guild.id, message.author.id, message.content
        )

        if sent_reason:
            reasons.append(sent_reason)

        total = round(struct_delta + sent_delta, 2)
        return total, ", ".join(reasons) if reasons else "routine activity"

    def _is_support_member(self, user_id: int) -> bool:
        support_guild = self.bot.get_guild(SUPPORT_GUILD_ID)
        return support_guild is not None and support_guild.get_member(user_id) is not None

    async def _get_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if role:
            return role
        key = (guild.id, name)
        if key not in self._role_locks:
            self._role_locks[key] = asyncio.Lock()
        async with self._role_locks[key]:
            role = discord.utils.get(guild.roles, name=name)
            if not role:
                role = await guild.create_role(name=name)
        return role

    async def _announce_bracket_promotion(self, guild: discord.Guild):
        new_bracket = await self.db.check_and_update_bracket(guild.id)
        if not new_bracket:
            return
        channel = guild.system_channel
        if channel is None:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if channel is None:
            return
        embed = discord.Embed(color=0xFFD700, title="NATIONAL BRACKET ELEVATED", description="中华人民共和国社会信用局")
        embed.add_field(name="NATION", value=guild.name, inline=True)
        embed.add_field(name="BRACKET", value=new_bracket, inline=True)
        embed.add_field(name="REGISTRY", value="`/serverrank top` · `/serverrank me`", inline=False)
        embed.set_thumbnail(url="attachment://security.png")
        try:
            await channel.send(embed=embed, file=discord.File("images/security.png", filename="security.png"))
        except discord.Forbidden:
            pass

    _RANK_HYSTERESIS = 3.0

    async def _handle_rank_change(self, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, old: float, new: float, from_message: bool = False):
        old_rank = get_rank(old)
        new_rank = get_rank(new)
        if old_rank["name"] == new_rank["name"]:
            return

        promoted = new > old
        if not promoted and new > old_rank["min"] - self._RANK_HYSTERESIS:
            return
        old_idx = get_rank_index(old_rank["name"])
        new_idx = get_rank_index(new_rank["name"])

        await self.db.log_rank_departure(guild.id, member.id, old_rank["name"])

        if promoted:
            yuan_earned = await self.db.handle_rank_promotion(
                guild.id, member.id, new_idx, RANK_YUAN[new_idx]
            )
            yuan_label = f"+¥{yuan_earned:,}" if yuan_earned > 0 else "¥0 · reward already claimed"
        else:
            penalty = RANK_YUAN[old_idx]
            await self.db.adjust_yuan(guild.id, member.id, -penalty)
            await self.db.set_rank_entered_at(guild.id, member.id)
            yuan_label = f"-¥{penalty:,}"

        if await self.db.get_assign_rank_roles(guild.id):
            try:
                new_role = await self._get_or_create_role(guild, new_rank["name"]) if new > EXECUTION_THRESHOLD else None
                updated = [r for r in member.roles if r.name != old_rank["name"]]
                if new_role and new_role not in updated:
                    updated.append(new_role)
                await member.edit(roles=updated)
            except discord.Forbidden:
                pass

        if promoted:
            await unlock_achievement(self.bot, guild, member, "first_promotion", channel=channel)
            if new_rank["name"] == RANKS[-1]["name"]:
                await unlock_achievement(self.bot, guild, member, "top_rank", channel=channel)
                if old_rank["name"] == RANKS[0]["name"]:
                    await unlock_achievement(self.bot, guild, member, "fastest_climb", channel=channel)

        if not from_message:
            await cache_set(
                f"rankembed:{guild.id}:{member.id}",
                json.dumps({"promoted": promoted, "old_rank": old_rank["name"], "new_rank": new_rank["name"], "yuan_label": yuan_label, "score": new}),
                ex=86400,
            )
            return

        if await self.db.get_rank_announcements_enabled(guild.id):
            await self._post_rank_embed(guild, member, channel, promoted, old_rank, new_rank, yuan_label, new)

    async def _post_rank_embed(self, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, promoted: bool, old_rank: dict, new_rank: dict, yuan_label: str, score: float):
        rank_channel_id = await self.db.get_rank_announcement_channel(guild.id)
        rank_channel = guild.get_channel(rank_channel_id) if rank_channel_id else None
        announce_channel = rank_channel or channel
        if not announce_channel:
            return

        if promoted:
            try:
                avatar_bytes = None
                try:
                    url = str(member.display_avatar.replace(size=256).url)
                    async with self._session.get(url, timeout=aiohttp.ClientTimeout(total=5)) as resp:
                        if resp.status == 200:
                            avatar_bytes = await resp.read()
                except Exception:
                    pass

                badge_label = None
                try:
                    badges = await self.bot.db.get_cosmetic_badges(member.id)
                    if badges:
                        pref = await self.bot.db.get_badge_preference(member.id)
                        owned = {b["badge"] for b in badges}
                        chosen = pref["badge_id"] if pref and pref["badge_id"] in owned else None
                        if not chosen:
                            for bid in ["voter", "verified", "figure", "influencer", "associate", "asset"]:
                                if bid in owned:
                                    chosen = bid
                                    break
                        if chosen and chosen in COSMETIC_META:
                            badge_label = COSMETIC_META[chosen]["label"]
                except Exception:
                    pass

                loop = asyncio.get_event_loop()
                png = await loop.run_in_executor(None, lambda: render_rank_card(
                    old_rank=old_rank["name"],
                    new_rank=new_rank["name"],
                    username=member.display_name,
                    score=score,
                    yuan_label=yuan_label,
                    avatar_bytes=avatar_bytes,
                    badge_label=badge_label,
                    bot_name=self.bot.user.name,
                ))
                file = discord.File(io.BytesIO(png), filename="rank_card.png")
                embed = discord.Embed(color=0xCC0000, title="STANDING ELEVATED", description="中华人民共和国社会信用局")
                embed.set_author(name=await self.bot.format_user_full(member, guild.id), icon_url=member.display_avatar.url)
                embed.set_image(url="attachment://rank_card.png")
                embed.set_footer(text="/vote on top.gg for bonus Yuan and score · GLORY TO THE CCP!")
                await announce_channel.send(member.mention, embed=embed, file=file)
            except discord.Forbidden:
                pass
        else:
            embed = discord.Embed(color=0x888888, title="STANDING REDUCED", description="中华人民共和国社会信用局")
            embed.add_field(name="CITIZEN", value=await self.bot.format_user_full(member, guild.id), inline=False)
            embed.add_field(name="PENALTY", value=f"{yuan_label} · Standing reduced to {new_rank['name']}", inline=False)
            embed.set_thumbnail(url="attachment://rank.png")
            embed.set_footer(text="ccp rankchannel [#channel] · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            try:
                await announce_channel.send(embed=embed, file=discord.File("images/rank.png", filename="rank.png"))
            except discord.Forbidden:
                pass

    async def _flush_pending_rank_embed(self, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel):
        key = f"rankembed:{guild.id}:{member.id}"
        raw = await cache_get(key)
        if not raw:
            return
        await cache_delete(key)
        try:
            data = json.loads(raw)
        except Exception:
            return
        old_rank = next((rk for rk in RANKS if rk["name"] == data["old_rank"]), None)
        new_rank = next((rk for rk in RANKS if rk["name"] == data["new_rank"]), None)
        if not old_rank or not new_rank:
            return
        await self._post_rank_embed(guild, member, channel, data["promoted"], old_rank, new_rank, data["yuan_label"], data["score"])

    async def _handle_execution_status(self, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, old: float, new: float):
        exec_role_name = "Execution Date: Tomorrow"
        existing_exec_role = discord.utils.get(guild.roles, name=exec_role_name)
        has_exec_role = existing_exec_role in member.roles if existing_exec_role else False

        entered = new <= EXECUTION_THRESHOLD and not has_exec_role
        recovered = new > EXECUTION_THRESHOLD + 1.0 and has_exec_role
        if not entered and not recovered:
            return

        try:
            exec_channel_id = await self.db.get_execution_channel(guild.id)
            exec_channel = guild.get_channel(exec_channel_id) if exec_channel_id else None
            target = exec_channel or channel

            exec_announce = await self.db.get_execution_announcements_enabled(guild.id)

            if entered:
                exec_role = await self._get_or_create_role(guild, exec_role_name)
                rank_names = {r["name"] for r in RANKS}
                updated = [r for r in member.roles if r.name not in rank_names]
                if exec_role not in updated:
                    updated.append(exec_role)
                await member.edit(roles=updated)

                confiscated = await self.db.confiscate_yuan(guild.id, member.id)

                if exec_announce:
                    citizen_str = await self.bot.format_user_full(member, guild.id)
                    embed = discord.Embed(color=0x111111, title="DETENTION ORDER ISSUED", description="中华人民共和国社会信用局")
                    embed.add_field(name="CITIZEN", value=f"{citizen_str} · {new:.2f}", inline=False)
                    if confiscated > 0:
                        embed.add_field(name="ASSETS", value=f"¥{confiscated:,} confiscated.", inline=False)
                    embed.set_thumbnail(url="attachment://security.png")
                    embed.timestamp = discord.utils.utcnow()
                    await target.send(embed=embed, file=discord.File("images/security.png", filename="security.png"))

                exec_count = await self.db.increment_execution_count(guild.id, member.id)
                if exec_count >= 3:
                    await unlock_achievement(self.bot, guild, member, "execution_regular", channel=target)

            else:
                if existing_exec_role and existing_exec_role in member.roles:
                    await member.remove_roles(existing_exec_role)

                correct_rank = get_rank(new)
                if await self.db.get_assign_rank_roles(guild.id):
                    correct_role = await self._get_or_create_role(guild, correct_rank["name"])
                    await member.add_roles(correct_role)

                if exec_announce:
                    citizen_str = await self.bot.format_user_full(member, guild.id)
                    embed = discord.Embed(color=0xCC0000, title="DETENTION ORDER RESCINDED", description="中华人民共和国社会信用局")
                    embed.add_field(name="CITIZEN", value=f"{citizen_str} · {new:.2f} · {correct_rank['name']}", inline=False)
                    embed.set_thumbnail(url="attachment://security.png")
                    embed.timestamp = discord.utils.utcnow()
                    await target.send(embed=embed, file=discord.File("images/security.png", filename="security.png"))
                await unlock_achievement(self.bot, guild, member, "survived_execution", channel=target)

        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid, uid = message.guild.id, message.author.id

        if await self.db.is_opted_out(uid):
            return

        skip = self._should_skip(message)
        if skip:
            struct_delta, reasons = 0.0, []
        else:
            struct_delta, reasons = self._structural_score(message)
        is_flagged = bool(reasons)
        is_support = self._is_support_member(uid)

        await cache_set(f"membername:{gid}:{uid}", message.author.display_name, ex=86400 * 7)
        vote_boost = bool(await cache_get(f"voteboost:{uid}"))
        yuan_gain = 0 if is_flagged else YUAN_PER_MESSAGE
        if yuan_gain > 0:
            if is_support:
                yuan_gain = round(yuan_gain * SUPPORT_YUAN_MULTIPLIER)
            if vote_boost:
                yuan_gain *= 2
            yuan_gain = await self._apply_yuan_diminishing(gid, uid, yuan_gain, exempt=is_support)
        user_row = await self.db.tick_user(gid, uid, yuan_gain)

        if user_row and user_row["message_count"] == 1:
            asyncio.create_task(self._announce_bracket_promotion(message.guild))

        if await self.db.get_effect(gid, uid, "freeze"):
            return

        if skip:
            delta, reason = 0.0, "skipped"
        else:
            delta, reason = await self._evaluate(message, struct_delta, reasons)

        if "positive sentiment" in reason:
            val = await self.db.increment_counter(uid, "messages_positive")
            await check_milestone(self.bot, message.guild, message.author, "messages_positive", val, channel=message.channel)
        elif "negative sentiment" in reason:
            val = await self.db.increment_counter(uid, "messages_negative")
            await check_milestone(self.bot, message.guild, message.author, "messages_negative", val, channel=message.channel)
        elif "civic participation" in reason:
            val = await self.db.increment_counter(uid, "messages_neutral")
            await check_milestone(self.bot, message.guild, message.author, "messages_neutral", val, channel=message.channel)

        if reason == "counter-revolutionary speech" and random.random() < 0.0001:
            try:
                await message.channel.send("https://tenor.com/view/social-credit-gif-3627510818063303442")
            except discord.Forbidden:
                pass

        if delta == 0:
            return

        track_key = f"dailytrack:{gid}:{uid}"
        now_ts = int(time.time())
        today_start = now_ts // 86400 * 86400
        seconds_to_midnight = 86400 - (now_ts % 86400)
        raw_tracking = await cache_get(track_key)
        if raw_tracking is None:
            daily_net, msg_count = 0.0, 0
        else:
            tracking = json.loads(raw_tracking)
            if tracking["day"] != today_start:
                daily_net, msg_count = 0.0, 0
            else:
                daily_net, msg_count = tracking["net"], tracking["count"]

        if delta > 0:
            if vote_boost:
                delta = round(delta * 2, 2)
            if daily_net >= DAILY_NET_DIMINISHING_THRESHOLD:
                delta = round(delta * DAILY_MSG_DIMINISHING_FACTOR, 2)
            effective_cap = DAILY_MSG_SCORE_CAP * (2 if vote_boost else 1)
            headroom = effective_cap - daily_net
            if headroom <= 0.0:
                await cache_set(
                    track_key,
                    json.dumps({"day": today_start, "net": daily_net, "count": msg_count}),
                    ex=seconds_to_midnight,
                )
                return
            delta = round(min(delta, headroom), 2)
            await cache_set(
                track_key,
                json.dumps({"day": today_start, "net": daily_net + delta, "count": msg_count + 1}),
                ex=seconds_to_midnight,
            )
        else:
            delta, _ = await self.db.apply_defense_chain(gid, uid, delta)
            await cache_set(
                track_key,
                json.dumps({"day": today_start, "net": daily_net + delta, "count": msg_count}),
                ex=seconds_to_midnight,
            )

        if delta == 0:
            return

        old_score, new_score = await self.db.update_score(gid, uid, delta, reason)

        if delta < 0:
            await self.db.record_negative_action(uid)
            log_cid = await self.db.get_score_log_channel(gid)
            if log_cid:
                log_ch = message.guild.get_channel(log_cid)
                if log_ch:
                    try:
                        content_preview = message.content[:200] if message.content else ""
                        await log_ch.send(
                            f"⚠️ {message.author.mention} `{delta:+.2f}` · **{new_score:.2f}** · {reason}\n> {content_preview}\n{message.jump_url}",
                            allowed_mentions=discord.AllowedMentions(users=False),
                        )
                    except discord.Forbidden:
                        pass
        else:
            clean_days = await self.db.get_clean_streak_days(uid)
            if clean_days is not None:
                await check_milestone(self.bot, message.guild, message.author, "clean_streak_days", clean_days, channel=message.channel)

        await self._flush_pending_rank_embed(message.guild, message.author, message.channel)
        self.bot.dispatch("score_change", message.guild, message.author, message.channel, old_score, new_score, True)
        await self.db.clean_expired_effects()

    @commands.Cog.listener()
    async def on_score_change(self, guild: discord.Guild, member: discord.Member, channel, old: float, new: float, from_message: bool = False):
        await self._handle_rank_change(guild, member, channel, old, new, from_message)
        await self._handle_execution_status(guild, member, channel, old, new)


async def setup(bot: commands.Bot):
    await bot.add_cog(Scoring(bot))
