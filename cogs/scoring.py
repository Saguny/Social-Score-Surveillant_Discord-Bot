import aiohttp
import discord
from discord.ext import commands
from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from langdetect import detect, LangDetectException
from config.ranks import get_rank
from config.rules import STRUCTURAL_RULES, SENTIMENT_SCALE, SENTIMENT_NEUTRAL_THRESHOLD, YUAN_PER_MESSAGE

TRANSLATE_URL = "https://translate.googleapis.com/translate_a/single"


class Scoring(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._last_messages: dict[tuple, str] = {}
        self._analyzer = SentimentIntensityAnalyzer()
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()

    async def cog_unload(self):
        if self._session:
            await self._session.close()
            self._session = None

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

    async def _sentiment_score(self, text: str) -> tuple[float, str | None]:
        if len(text.strip()) < 4:
            return 0.0, None
        try:
            lang = detect(text)
        except LangDetectException:
            return 0.0, None

        english = text if lang == "en" else await self._translate_to_english(text)

        compound = self._analyzer.polarity_scores(english)["compound"]
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
        sent_delta, sent_reason = await self._sentiment_score(message.content)

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

        if reason != "skipped" and await self.db.get_web_consent(gid):
            self.db.log_message(gid, uid, str(message.author), message.content, delta, reason)

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
