import asyncio
import concurrent.futures
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
)
from config.banned_topics import contains_banned_topic
from cogs.achievements import unlock as unlock_achievement, check_milestone
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

    async def _evaluate(self, message: discord.Message) -> tuple[float, str]:
        content = message.content.lower().strip()

        if content.startswith("http") and " " not in content:
            return 0.0, "skipped"
        if not content and (message.attachments or message.stickers):
            return 0.0, "skipped"

        struct_delta, reasons = self._structural_score(message)
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
        if not role:
            role = await guild.create_role(name=name)
        return role

    async def _handle_rank_change(self, guild: discord.Guild, member: discord.Member, channel: discord.TextChannel, old: float, new: float):
        old_rank = get_rank(old)
        if new >= old:
            new_rank = get_rank(new)
        elif new <= old_rank["min"] - 1.0:
            new_rank = get_rank(new)
        else:
            new_rank = old_rank
        if old_rank["name"] == new_rank["name"]:
            return

        promoted = new > old
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
                old_role = discord.utils.get(guild.roles, name=old_rank["name"])
                if old_role and old_role in member.roles:
                    await member.remove_roles(old_role)
                if new > EXECUTION_THRESHOLD:
                    new_role = await self._get_or_create_role(guild, new_rank["name"])
                    await member.add_roles(new_role)
            except discord.Forbidden:
                pass

        if promoted:
            await unlock_achievement(self.bot, guild, member, "first_promotion", channel=channel)
            if new_rank["name"] == RANKS[-1]["name"]:
                await unlock_achievement(self.bot, guild, member, "top_rank", channel=channel)
                if old_rank["name"] == RANKS[0]["name"]:
                    await unlock_achievement(self.bot, guild, member, "fastest_climb", channel=channel)

        color = 0xFFD700 if promoted else 0xCC0000
        status = "PROMOTED" if promoted else "DEMOTED"

        embed = discord.Embed(color=color, title="中华人民共和国社会信用局")
        embed.add_field(name="CITIZEN", value=await self.bot.format_user_full(member, guild.id), inline=False)
        embed.add_field(
            name=f"STATUS CHANGE: {status}",
            value=f"{old_rank['name']} -> {new_rank['name']}\nScore: {new:.2f} · {yuan_label}",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        try:
            await channel.send(embed=embed)
        except discord.Forbidden:
            pass

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

            if entered:
                exec_role = await self._get_or_create_role(guild, exec_role_name)
                for rank in RANKS:
                    r = discord.utils.get(guild.roles, name=rank["name"])
                    if r and r in member.roles:
                        await member.remove_roles(r)
                await member.add_roles(exec_role)

                confiscated = await self.db.confiscate_yuan(guild.id, member.id)
                citizen_str = await self.bot.format_user_full(member, guild.id)

                embed = discord.Embed(
                    color=0x8B0000, 
                    title="🚨 中华人民共和国社会信用局 · NOTICE OF TERMINATION",
                    description=f"**Citizen:** {citizen_str}\n**Current Score:** `{new:.2f}`"
                )
                
                status_text = (
                    " **CRITICAL INFRACTION DETECTED**\n"
                    "Your social credit score has gone below 610-. You have been placed on the **Execution List** by the Bureau.\n"
                    f"Your Role has been assigned."
                )
                embed.add_field(name="SURVEILLANCE STATUS", value=status_text, inline=False)
                
                if confiscated > 0:
                    embed.add_field(
                        name="STATE CONFISCATION", 
                        value=f"All assets totaling **¥{confiscated:,}** have been seized and redistributed evenly to compliant citizens.", 
                        inline=False
                    )
                
                embed.timestamp = discord.utils.utcnow()
                if not exec_channel_id:
                    embed.set_footer(text="System Notice: Use 'ccp executions #channel' to assign a dedicated firing squad channel.")
                else:
                    embed.set_footer(text="中华人民共和国社会信用局 · ALL ACTIONS RECORDED")
                
                await target.send(content=f"{member.mention} **The Eternal Chairman awaits your Execution with Joy.**", embed=embed)

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
                
                citizen_str = await self.bot.format_user_full(member, guild.id)
                
                embed = discord.Embed(
                    color=0x008000,
                    title="🇨🇳 中华人民共和国社会信用局 · PROBATION UPDATE",
                    description=f"**Citizen:** {citizen_str}\n**Current Score:** `{new:.2f}` (`{correct_rank['name']}`)"
                )
                embed.add_field(
                    name="REHABILITATION SUCCESSFUL",
                    value=f"Citizen has successfully recovered above the threshold. The execution order has been rescinded and the `{exec_role_name}` role removed.",
                    inline=False
                )
                embed.timestamp = discord.utils.utcnow()
                embed.set_footer(text="GLORY TO THE CCP!")
                
                await target.send(embed=embed)
                await unlock_achievement(self.bot, guild, member, "survived_execution", channel=target)

        except discord.Forbidden:
            pass

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid, uid = message.guild.id, message.author.id

        yuan_gain = YUAN_PER_MESSAGE
        if self._is_support_member(uid):
            yuan_gain = round(yuan_gain * SUPPORT_YUAN_MULTIPLIER)
        await self.db.tick_user(gid, uid, yuan_gain)

        if await self.db.get_effect(gid, uid, "freeze"):
            return

        delta, reason = await self._evaluate(message)

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
            if daily_net >= DAILY_NET_DIMINISHING_THRESHOLD:
                delta = round(delta * DAILY_MSG_DIMINISHING_FACTOR, 2)
            headroom = DAILY_MSG_SCORE_CAP - daily_net
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

        broadcast_media = False
        if delta > 0 and await self.db.get_effect(gid, uid, "media_coverage"):
            await self.db.consume_effect(gid, uid, "media_coverage")
            delta = round(delta * 2, 2)
            broadcast_media = True

        old_score, new_score = await self.db.update_score(gid, uid, delta, reason)

        if delta < 0:
            await self.db.record_negative_action(uid)
        else:
            clean_days = await self.db.get_clean_streak_days(uid)
            if clean_days is not None:
                await check_milestone(self.bot, message.guild, message.author, "clean_streak_days", clean_days, channel=message.channel)

        if broadcast_media:
            embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 国家媒体报道")
            embed.add_field(
                name="STATE MEDIA SPOTLIGHT",
                value=f"{await self.bot.format_user_full(message.author, message.guild.id)} · +{delta:.2f} score · DOUBLED BY STATE MEDIA",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await message.channel.send(embed=embed)

        self.bot.dispatch("score_change", message.guild, message.author, message.channel, old_score, new_score)
        await self.db.clean_expired_effects()

    @commands.Cog.listener()
    async def on_score_change(self, guild: discord.Guild, member: discord.Member, channel, old: float, new: float):
        await self._handle_rank_change(guild, member, channel, old, new)
        await self._handle_execution_status(guild, member, channel, old, new)


async def setup(bot: commands.Bot):
    await bot.add_cog(Scoring(bot))
