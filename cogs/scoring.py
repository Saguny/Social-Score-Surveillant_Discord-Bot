import asyncio
import concurrent.futures
import os
import time
import aiohttp
import discord
from discord.ext import commands
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from config.ranks import get_rank
from config.rules import STRUCTURAL_RULES, SENTIMENT_SCALE, SENTIMENT_NEUTRAL_THRESHOLD, YUAN_PER_MESSAGE
from config.banned_topics import contains_banned_topic

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"
_LANG_CACHE_TTL = 3600

_module_analyzer = SentimentIntensityAnalyzer()
_worker_analyzer: SentimentIntensityAnalyzer | None = None


def _init_worker():
    global _worker_analyzer
    _worker_analyzer = SentimentIntensityAnalyzer()


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

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=min(4, max(2, os.cpu_count() or 2)),
            initializer=_init_worker,
        )

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

        for rule in STRUCTURAL_RULES:
            t = rule["type"]

            if t == "spam":
                if self._last_messages.get(key) == content:
                    total += rule["delta"]
                    reasons.append(rule["reason"])

            elif t == "caps":
                raw = message.content
                if len(raw) >= rule["min_length"]:
                    letters = [c for c in raw if c.isalpha()]
                    if letters and sum(1 for c in letters if c.isupper()) / len(letters) >= rule["threshold"]:
                        total += rule["delta"]
                        reasons.append(rule["reason"])

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

        if abs(compound) < SENTIMENT_NEUTRAL_THRESHOLD:
            return 0.0, None
        return round(compound * SENTIMENT_SCALE, 2), "positive sentiment" if compound > 0 else "negative sentiment"

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

    async def _get_or_create_role(self, guild: discord.Guild, name: str) -> discord.Role:
        role = discord.utils.get(guild.roles, name=name)
        if not role:
            role = await guild.create_role(name=name)
        return role

    async def _handle_rank_change(self, message: discord.Message, old: float, new: float):
        old_rank = get_rank(old)
        new_rank = get_rank(new)
        if old_rank["name"] == new_rank["name"]:
            return

        promoted = new > old

        try:
            old_role = discord.utils.get(message.guild.roles, name=old_rank["name"])
            new_role = await self._get_or_create_role(message.guild, new_rank["name"])
            if old_role and old_role in message.author.roles:
                await message.author.remove_roles(old_role)
            await message.author.add_roles(new_role)
        except discord.Forbidden:
            pass

        color = 0xFFD700 if promoted else 0xCC0000
        status = "PROMOTED" if promoted else "DEMOTED"

        embed = discord.Embed(color=color, title="中华人民共和国社会信用局")
        embed.add_field(name="CITIZEN", value=str(message.author), inline=False)
        embed.add_field(
            name=f"STATUS CHANGE: {status}",
            value=f"{old_rank['name']} → {new_rank['name']}\nScore: {new:.2f}",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await message.channel.send(embed=embed)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return

        gid, uid = message.guild.id, message.author.id

        await self.db.tick_user(gid, uid, YUAN_PER_MESSAGE)

        if await self.db.get_effect(gid, uid, "freeze"):
            return

        delta, reason = await self._evaluate(message)

        if delta == 0:
            return

        old_score, new_score = await self.db.update_score(gid, uid, delta, reason)

        watchers = await self.db.get_surveillance_watchers(gid, uid)
        for watcher_id in watchers:
            watcher = message.guild.get_member(watcher_id)
            if watcher:
                try:
                    direction = "▲" if delta > 0 else "▼"
                    await watcher.send(
                        f"**[SURVEILLANCE REPORT]**\n"
                        f"Citizen {message.author} · {direction} {abs(delta):.2f}\n"
                        f"Current score: {new_score:.2f}"
                    )
                except Exception:
                    pass

        await self._handle_rank_change(message, old_score, new_score)
        await self.db.clean_expired_effects()


async def setup(bot: commands.Bot):
    await bot.add_cog(Scoring(bot))
