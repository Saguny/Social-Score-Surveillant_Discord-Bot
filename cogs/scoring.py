import asyncio
import concurrent.futures
import os
import random
import time
import aiohttp
import discord
from discord.ext import commands, tasks
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config.ranks import get_rank, get_rank_index, RANKS, EXECUTION_THRESHOLD, RANK_YUAN
from config.rules import (
    SPAM_MIN_LENGTH, SPAM_DELTA, CAPS_MIN_LENGTH, CAPS_THRESHOLD, CAPS_DELTA,
    SENTIMENT_SCALE, SENTIMENT_NEUTRAL_THRESHOLD, NEUTRAL_BONUS, YUAN_PER_MESSAGE,
    DAILY_MSG_SCORE_CAP, DAILY_NET_DIMINISHING_THRESHOLD, DAILY_MSG_DIMINISHING_FACTOR,
    SUPPORT_GUILD_ID, SUPPORT_YUAN_MULTIPLIER,
)
from config.banned_topics import contains_banned_topic

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
        self._lang_cache: dict[tuple, tuple[str, float]] = {}
        self._pos_streaks: dict[tuple[int, int], int] = {}
        self._daily_tracking: dict[tuple[int, int], tuple[int, float, int]] = {}

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(4, max(2, os.cpu_count() or 2)),
            initializer=_init_worker,
        )
        self._cache_cleanup.start()

    async def cog_unload(self):
        self._cache_cleanup.cancel()
        if self._session:
            await self._session.close()
            self._session = None
        if self._executor:
            self._executor.shutdown(wait=False)
            self._executor = None

    @tasks.loop(hours=1)
    async def _cache_cleanup(self):
        now             = time.time()
        today_start     = int(now) // 86400 * 86400
        lang_cutoff     = now - _LANG_CACHE_TTL
        stale_lang      = [k for k, v in self._lang_cache.items() if v[1] < lang_cutoff]
        stale_tracking  = [k for k, v in self._daily_tracking.items() if v[0] < today_start]
        for k in stale_lang:     del self._lang_cache[k]
        for k in stale_tracking: del self._daily_tracking[k]

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
        now = time.time()
        cache_key = (guild_id, user_id)
        cached = self._lang_cache.get(cache_key)

        if cached and now - cached[1] < _LANG_CACHE_TTL:
            lang = cached[0]
            english = text if lang == "en" else await self._translate_to_english(text)
            if contains_banned_topic(english):
                return -SENTIMENT_SCALE, "counter-revolutionary speech"
            compound = await loop.run_in_executor(self._executor, _vader_only, english)
        else:
            lang, compound = await loop.run_in_executor(self._executor, _run_in_worker, text)
            self._lang_cache[cache_key] = (lang, now)
            english = text if lang == "en" else await self._translate_to_english(text)
            if contains_banned_topic(english):
                return -SENTIMENT_SCALE, "counter-revolutionary speech"
            if lang != "en":
                compound = await loop.run_in_executor(self._executor, _vader_only, english)

        key = (guild_id, user_id)
        if abs(compound) < SENTIMENT_NEUTRAL_THRESHOLD:
            self._pos_streaks.pop(key, None)
            return NEUTRAL_BONUS, "civic participation"

        delta = round(compound * SENTIMENT_SCALE, 2)
        if delta > 0:
            streak = self._pos_streaks.get(key, 0) + 1
            self._pos_streaks[key] = streak
            if streak >= 3:
                multiplier = 1.0 + min(streak // 3, 5) * 0.1
                delta = round(delta * multiplier, 2)
        else:
            self._pos_streaks.pop(key, None)
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
        entered = old > EXECUTION_THRESHOLD and new <= EXECUTION_THRESHOLD
        recovered = old <= EXECUTION_THRESHOLD and new > EXECUTION_THRESHOLD + 1.0
        if not entered and not recovered:
            return

        exec_role_name = "Execution Date: Tomorrow"
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

            else:
                exec_role = discord.utils.get(guild.roles, name=exec_role_name)
                if exec_role and exec_role in member.roles:
                    await member.remove_roles(exec_role)
                
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

        if reason == "counter-revolutionary speech" and random.random() < 0.0001:
            try:
                await message.channel.send("https://tenor.com/view/social-credit-gif-3627510818063303442")
            except discord.Forbidden:
                pass

        if delta == 0:
            return

        key = (gid, uid)
        today_start = int(time.time()) // 86400 * 86400
        tracking = self._daily_tracking.get(key)
        if tracking is None or tracking[0] != today_start:
            daily_net, msg_count = 0.0, 0
        else:
            _, daily_net, msg_count = tracking

        if delta > 0:
            if daily_net >= DAILY_NET_DIMINISHING_THRESHOLD:
                delta = round(delta * DAILY_MSG_DIMINISHING_FACTOR, 2)
            headroom = DAILY_MSG_SCORE_CAP - daily_net
            if headroom <= 0.0:
                self._daily_tracking[key] = (today_start, daily_net, msg_count)
                return
            delta = round(min(delta, headroom), 2)
            self._daily_tracking[key] = (today_start, daily_net + delta, msg_count + 1)
        else:
            delta, _ = await self.db.apply_defense_chain(gid, uid, delta)
            self._daily_tracking[key] = (today_start, daily_net + delta, msg_count)

        if delta == 0:
            return

        broadcast_media = False
        if delta > 0 and await self.db.get_effect(gid, uid, "media_coverage"):
            await self.db.consume_effect(gid, uid, "media_coverage")
            delta = round(delta * 2, 2)
            broadcast_media = True

        old_score, new_score = await self.db.update_score(gid, uid, delta, reason)

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
