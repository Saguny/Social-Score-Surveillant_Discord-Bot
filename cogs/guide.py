import re
import random
from datetime import datetime, timezone
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config.ranks import RANKS

REPO_URL      = "https://github.com/Saguny/Social-Score-Surveillant_Discord-Bot"
INVITE_URL    = "https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=8&integration_type=0&scope=bot"
WIKIQUOTE_API = "https://en.wikiquote.org/w/api.php"

FALLBACK_DECREES = [
    "The Chinese dream is an dream of the whole nation, as well as of every individual.",
    "Power must be caged by the system.",
    "We must make persistent efforts, press ahead with indomitable will, continue to push forward the great cause of socialism with Chinese characteristics.",
    "To realize the great rejuvenation of the Chinese nation is the greatest dream for the Chinese nation in modern history.",
    "Harmony is not a suggestion. It is a measurement.",
]

CREDITS_LINES = [
    ("discord.py 2.x",    "Bot framework · https://discordpy.readthedocs.io"),
    ("asyncpg",           "PostgreSQL driver · https://magicstack.github.io/asyncpg"),
    ("vaderSentiment",    "Sentiment analysis · https://github.com/cjhutto/vaderSentiment"),
    ("langdetect",        "Language detection · https://github.com/Mimino666/langdetect"),
    ("aiohttp",           "Async HTTP · https://docs.aiohttp.org"),
    ("python-dotenv",     "Environment config · https://github.com/theskumar/python-dotenv"),
]


class Guide(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot    = bot
        self._quotes: list[str] = []
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self):
        self._session = aiohttp.ClientSession()
        self._refresh_quotes.start()

    async def cog_unload(self):
        self._refresh_quotes.cancel()
        if self._session:
            await self._session.close()

    async def _fetch_quotes(self):
        try:
            params = {"action": "parse", "page": "Xi_Jinping", "prop": "wikitext", "format": "json"}
            async with self._session.get(WIKIQUOTE_API, params=params, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json()
            wikitext = data["parse"]["wikitext"]["*"]
            quotes = []
            for line in wikitext.splitlines():
                if line.startswith("*") and not line.startswith("**"):
                    q = line.lstrip("*").strip()
                    q = re.sub(r"\[\[(?:[^|\]]*\|)?([^\]]+)\]\]", r"\1", q)
                    q = re.sub(r"\{\{[^}]+\}\}", "", q)
                    q = re.sub(r"'''?", "", q)
                    q = re.sub(r"<[^>]+>", "", q)
                    q = q.strip()
                    if 20 < len(q) < 500:
                        quotes.append(q)
            if quotes:
                self._quotes = quotes
        except Exception:
            pass

    @tasks.loop(hours=24)
    async def _refresh_quotes(self):
        await self._fetch_quotes()

    @_refresh_quotes.before_loop
    async def _before_refresh(self):
        await self.bot.wait_until_ready()

    @app_commands.command(name="guide", description="Full guide to the Social Credit System")
    async def guide(self, interaction: discord.Interaction):
        embeds = []

        e1 = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CITIZEN GUIDE")
        e1.description = (
            "Your social credit score is tracked silently. Every message you send is evaluated. "
            "Score changes accumulate slowly over time. Rank changes trigger an official bureau notification.\n\n"
            "Score range: 600 (floor) to 1300 (ceiling). Everyone starts at 750."
        )
        rank_lines = "\n".join(f"{r['min']} to {r['max']}   {r['name']}" for r in RANKS)
        e1.add_field(name="RANKS", value=f"```\n{rank_lines}\n```", inline=False)
        embeds.append(e1)

        e2 = discord.Embed(color=0xCC0000, title="SCORING RULES")
        e2.add_field(
            name="SENTIMENT",
            value=(
                "Each message is analyzed for tone. Positive messages nudge your score up, "
                "negative ones nudge it down. Max impact per message is +0.2 or -0.2. "
                "Neutral messages do nothing."
            ),
            inline=False,
        )
        e2.add_field(
            name="STRUCTURAL VIOLATIONS",
            value=(
                "Sending the same message twice in a row: -1.0\n"
                "Excessive caps on longer messages: -0.2\n"
                "Messages under 4 characters: -0.1"
            ),
            inline=False,
        )
        e2.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e2)

        e3 = discord.Embed(color=0xCC0000, title="SCORE AND STAT COMMANDS")
        e3.add_field(name="/score [citizen]",        value="View your score and current rank.", inline=False)
        e3.add_field(name="/stats [citizen]",        value="Full breakdown: trends, peak/low score, messages, report history.", inline=False)
        e3.add_field(name="/history [citizen]",      value="Last 5 score changes. Viewing others requires mod permissions.", inline=False)
        e3.add_field(name="/leaderboard",            value="Top 3 most compliant and top 3 greatest threats.", inline=False)
        e3.add_field(name="/state_report",           value="Server-wide report: biggest rise/fall, top informant, yuan in circulation, avg score.", inline=False)
        e3.add_field(name="/botinfo",                value="Technical information about the bot: creator, tech stack, server count, repo and invite links.", inline=False)
        e3.add_field(name="/uptime",                 value="How long the Bureau has been active since last restart.", inline=False)
        e3.add_field(name="/ping",                   value="Check the Bureau's response latency.", inline=False)
        e3.add_field(name="/decree",                 value="Receive an official proclamation from the Bureau.", inline=False)
        e3.add_field(name="/credits",                value="Open-source libraries powering the surveillance apparatus.", inline=False)
        embeds.append(e3)

        e4 = discord.Embed(color=0xCC0000, title="YUAN AND ECONOMY")
        e4.add_field(name="Earning Yuan",  value="You earn 1 Yuan per message automatically.", inline=False)
        e4.add_field(name="/yuan",         value="Check your Yuan balance and lifetime earned/spent.", inline=False)
        e4.add_field(name="/shop",         value="Browse available shop items and their costs.", inline=False)
        e4.add_field(
            name="/buy <item> [target] [text]",
            value=(
                "`report` (500) · Dock a citizen 2 score points. Files an official report.\n"
                "`denounce` (1000) · Post a public denouncement with a custom message (100 char max).\n"
                "`surveillance` (300) · Get a DM every time a target's score changes for 24 hours.\n"
                "`rehabilitate` (400+) · Recover 3 score points. Cost doubles each time you use it.\n"
                "`expunge` (600) · Wipe your last 5 score changes from public history.\n"
                "`freeze` (800) · Freeze your score for 1 hour. No changes will be applied.\n"
                "`propaganda` (350) · Bot posts a state-approved commendation of you in the channel."
            ),
            inline=False,
        )
        embeds.append(e4)

        e5 = discord.Embed(color=0xCC0000, title="SOCIAL RATING")
        e5.add_field(
            name="/endorse <citizen> [reason]",
            value="Grant a citizen a positive rating. Adjusts their score by +3.0. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.add_field(
            name="/rebuke <citizen> [reason]",
            value="Issue a negative rating against a citizen. Adjusts their score by -3.0. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e5)

        e6 = discord.Embed(color=0xCC0000, title="FUNDRAISERS")
        e6.description = (
            "A citizen proposes to do something in exchange for Yuan. Others donate. "
            "When the goal is hit, the organizer must follow through, then open a vote. "
            "If enough citizens confirm, they receive the funds. If enough deny, donors are refunded."
        )
        e6.add_field(name="/fundraise create <goal> <description>", value="Start a fundraiser. Set a Yuan goal and describe what you will do.", inline=False)
        e6.add_field(name="/fundraise donate <id> <amount>",        value="Donate Yuan to an open fundraiser. Cannot donate to your own.", inline=False)
        e6.add_field(name="/fundraise complete <id>",               value="Mark your funded fundraiser as complete. Opens the voting phase.", inline=False)
        e6.add_field(name="/fundraise vote <id> <confirm|deny>",    value="Vote on whether the organizer fulfilled their obligation. One vote per citizen.", inline=False)
        e6.add_field(name="/fundraise list",                        value="List all active fundraisers in this server.", inline=False)
        e6.add_field(name="/fundraise info <id>",                   value="View full details and vote tally for a specific fundraiser.", inline=False)
        embeds.append(e6)

        e7 = discord.Embed(color=0x333333, title="MOD COMMANDS")
        e7.description = "These are prefix commands. Type them directly in chat."
        e7.add_field(name="ccp initialize",                         value="Register all current server members into the system.", inline=False)
        e7.add_field(name="ccp adjust <@citizen> <delta> <reason>", value="Manually adjust a citizen's score by any amount.", inline=False)
        e7.add_field(name="ccp reset <@citizen>",                   value="Reset a citizen back to 750.", inline=False)
        e7.add_field(name="ccp threshold <n>",                      value="Set how many votes are required to resolve a fundraiser. Default is 3.", inline=False)
        e7.add_field(name="ccp webconsent <on|off>",                value="Enable or disable message logging for the web dashboard.", inline=False)
        e7.add_field(name="ccp poster",                              value="Display a random propaganda poster.", inline=False)
        e7.add_field(name="ccp posters",                             value="Toggle daily propaganda poster broadcasts in this channel. React ❤️ for +1 credit and +20 yuan · React 😡 for -1 credit.", inline=False)
        e7.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e7)

        await interaction.response.send_message(embeds=embeds, ephemeral=True)

    @app_commands.command(name="ping", description="Check the Bureau's response latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · SIGNAL CHECK",
            description=f"The Bureau responds in **{latency_ms} ms**. Your transmission has been logged.",
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="decree", description="Receive an official proclamation from the Bureau")
    async def decree(self, interaction: discord.Interaction):
        pool = self._quotes or FALLBACK_DECREES
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · OFFICIAL DECREE",
            description=f"*{random.choice(pool)}*",
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="credits", description="Open-source libraries powering the Bureau")
    async def credits(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · ACKNOWLEDGEMENTS",
            description="The surveillance apparatus is built on the following open-source technologies. The Party is grateful.",
        )
        for name, desc in CREDITS_LINES:
            e.add_field(name=name, value=desc, inline=False)
        e.add_field(
            name="SOURCE CODE",
            value=f"[GitHub]({REPO_URL})",
            inline=False,
        )
        await interaction.response.send_message(embed=e, ephemeral=True)

    @app_commands.command(name="uptime", description="How long the Bureau has been active")
    async def uptime(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        start_time = getattr(self.bot, "start_time", None)
        if start_time is None:
            await interaction.followup.send("The Bureau's records are unavailable.", ephemeral=True)
            return

        delta   = datetime.now(timezone.utc) - start_time
        days    = delta.days
        hours   = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        seconds = delta.seconds % 60

        parts = []
        if days:    parts.append(f"{days}d")
        if hours:   parts.append(f"{hours}h")
        if minutes: parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")

        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · BUREAU STATUS",
            description=f"The Bureau has been vigilant for **{' '.join(parts)}**.",
        )
        e.add_field(name="ONLINE SINCE", value=f"<t:{int(start_time.timestamp())}:F>", inline=False)

        await interaction.followup.send(embed=e, ephemeral=True)

    @app_commands.command(name="botinfo", description="Information about the Social Credit Bot")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)

        guild_count  = len(self.bot.guilds)
        member_count = sum(g.member_count or 0 for g in self.bot.guilds)
        latency_ms   = round(self.bot.latency * 1000)

        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · BOT INFORMATION",
            description=(
                "An authoritative CCP-themed social credit system for Discord. "
                "Every citizen is monitored. Every message is evaluated. Glory awaits the compliant."
            ),
        )

        e.add_field(
            name="CREATOR",
            value="saguny",
            inline=True,
        )
        e.add_field(
            name="SERVERS · CITIZENS",
            value=f"{guild_count} servers · {member_count:,} citizens",
            inline=True,
        )
        e.add_field(
            name="LATENCY",
            value=f"{latency_ms} ms",
            inline=True,
        )
        e.add_field(
            name="TECHNOLOGY",
            value=(
                "discord.py 2.x · PostgreSQL\n"
                "vaderSentiment · langdetect · deep-translate"
            ),
            inline=False,
        )
        e.add_field(
            name="LINKS",
            value=f"[Source Code]({REPO_URL}) · [Invite to Server]({INVITE_URL})",
            inline=False,
        )

        await interaction.followup.send(embed=e, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
