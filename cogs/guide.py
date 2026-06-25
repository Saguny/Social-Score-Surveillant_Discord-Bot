import re
import random
import time
from datetime import datetime, timezone
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config.ranks import RANKS
from config.market_hours import all_exchange_status as _all_exchange_status, EXCHANGE_NAMES as _EXCHANGE_NAMES

REPO_URL      = "https://github.com/Saguny/Social-Score-Surveillant_Discord-Bot"
INVITE_URL    = "https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=2416438352&integration_type=0&scope=bot"
TOPGG_URL     = "https://top.gg/bot/856163780265902151/invite"
SUPPORT_URL   = "https://discord.gg/invite/k4W6YAPYhC"
DASHBOARD_URL = "https://socialcredit-dashboard.up.railway.app"
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

_TOPIC_OPTIONS = [
    discord.SelectOption(label="Overview",          value="overview",     description="What is the Social Credit System?"),
    discord.SelectOption(label="Scoring Rules",     value="scoring",      description="How messages are evaluated"),
    discord.SelectOption(label="Ranks & Execution", value="ranks",        description="Rank tiers, execution list, prestige"),
    discord.SelectOption(label="Stat Commands",     value="stats",        description="/score, /stats, /leaderboard and more"),
    discord.SelectOption(label="Economy",           value="economy",      description="Yuan earning, transfers, battle, vote"),
    discord.SelectOption(label="Shop & Items",      value="shop",         description="/buy, key items, lottery tiers"),
    discord.SelectOption(label="Social Rating",     value="social",       description="/endorse, /rebuke, fundraisers"),
    discord.SelectOption(label="Markets",           value="markets",      description="Stocks, turbos, circuit breakers"),
    discord.SelectOption(label="Events & Posters",  value="events",       description="Propaganda events and daily posters"),
    discord.SelectOption(label="Achievements",      value="achievements", description="Achievement system overview"),
    discord.SelectOption(label="Mod Commands",      value="mod",          description="Mod-only commands and server settings"),
    discord.SelectOption(label="Privacy & Legal",   value="privacy",      description="/optout, /optin, and disclaimer"),
]


class GuideView(discord.ui.View):
    def __init__(self, exchange_status: dict):
        super().__init__(timeout=1800)
        self._exchange_status = exchange_status

    def build(self, topic: str) -> discord.Embed:
        e = getattr(self, f"_page_{topic}")()
        e.set_thumbnail(url="attachment://bureau.png")
        e.set_footer(text=f"{len(_TOPIC_OPTIONS)} sections, select a topic from the menu below · GLORY TO THE CCP!")
        return e

    @discord.ui.select(placeholder="Select a topic...", options=_TOPIC_OPTIONS)
    async def select_topic(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.edit_message(embed=self.build(select.values[0]))

    def _page_overview(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · OVERVIEW")
        e.description = (
            "A CCP-themed social credit system for Discord. Every message you send is evaluated by the Bureau. "
            "Your score determines your rank. Yuan is the currency of the state."
        )
        e.add_field(name="SCORE",     value="Starts at **750**. Range: 600–1300. Rises with positive messages, falls with negative ones.", inline=False)
        e.add_field(name="YUAN",      value=f"Earn ¥10 per message. Spend at `/shop` on items, protections, and more. [Support server]({SUPPORT_URL}) members earn +15%.", inline=False)
        e.add_field(name="FEATURES", value="Stocks · Achievements · Prestige · Global Rankings · Events", inline=False)
        e.add_field(name="GET STARTED", value="`/score` · `/stats` · `/checkin` · `/shop` · `/leaderboard`", inline=False)
        e.add_field(name="LINKS",     value=f"[Dashboard]({DASHBOARD_URL}) · [Support Server]({SUPPORT_URL}) · [Invite]({INVITE_URL})", inline=False)
        return e

    def _page_scoring(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · SCORING RULES")
        e.add_field(name="SENTIMENT",           value="Each message is analyzed for tone. Max impact: **+0.30** or **-0.30** per message. Neutral messages grant +0.03 for civic participation.", inline=False)
        e.add_field(name="POSITIVE STREAK",     value="Consecutive positive messages build a multiplier. Up to **1.5×** at streak 15+.", inline=False)
        e.add_field(name="STRUCTURAL",          value="Repeated message (10+ chars): **-0.70** · Excessive caps (80%+, 16+ chars): **-0.40**", inline=False)
        e.add_field(name="BANNED TOPICS",       value="References to Tiananmen, Taiwan independence, Xinjiang, Tibet, Falun Gong, and similar: **-0.30** regardless of tone.", inline=False)
        e.add_field(name="DAILY LIMIT",         value="Score gains cap at **+8.00 net per day**. At +6.00 net, further positive messages yield 25% effect. Penalties are always full strength.", inline=False)
        e.add_field(name="INACTIVITY DECAY",    value="Citizens inactive for 7+ days are nudged back toward 750 each day until they return.", inline=False)
        return e

    def _page_ranks(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · RANKS & EXECUTION")
        rank_lines = "\n".join(f"{r['min']:>4} – {r['max']:>4}  {r['name']}" for r in RANKS)
        e.add_field(name="RANK TIERS",      value=f"```\n{rank_lines}\n```", inline=False)
        e.add_field(name="EXECUTION LIST",  value="Score ≤ 610: assigned role **Execution Date: Tomorrow**, yuan confiscated and distributed. Recovery above 611 removes the role.", inline=False)
        e.add_field(name="RANK REWARDS",    value="Promotions award Yuan scaling with tier. Demotions deduct Yuan based on the rank you leave.", inline=False)
        e.add_field(name="RANK ROLES",      value="Rank roles auto-assign on score change. Mods can disable with `ccp roles off`. Execution List role is always active.", inline=False)
        e.add_field(name="/prestige",       value="At score **1290**, sacrifice it back to 750 for a permanent prestige star shown globally. Yuan resets to 0.", inline=False)
        return e

    def _page_stats(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · STAT COMMANDS")
        e.add_field(name="/score [citizen]",              value="Score, rank tier, server rank position (e.g. #3 of 120).", inline=False)
        e.add_field(name="/stats [citizen]",              value="3 pages — **Overview** (score, trends, rank streak) · **Social** (endorsements, rebukes) · **Economy** (yuan, lottery, check-in streak).", inline=False)
        e.add_field(name="/daily_report [citizen]",       value="Today's score: gains, losses, net, message counts, and yuan vs yesterday.", inline=False)
        e.add_field(name="/leaderboard",                  value="5 pages: Score · Economy · Activity · Social · Markets.", inline=False)
        e.add_field(name="/globalrank me",                value="Your cross-server standing: balance, avg score, total earned, global rank in all 4 categories.", inline=False)
        e.add_field(name="/globalrank top",               value="Global leaderboard: Top Balance · Top Earned · Top Score · Top Citizens. Also live on the web dashboard.", inline=False)
        e.add_field(name="/globalrank visibility <on|off>", value="Show or hide your name on the global leaderboard and dashboard.", inline=False)
        e.add_field(name="/state_report",                 value="Server-wide report: biggest rise/fall, yuan in circulation, active citizens.", inline=False)
        e.add_field(name="/graph <score|yuan> [citizen]", value="30-day trend graph. Yuan graph populates once per day.", inline=False)
        e.add_field(name="/checkin",                      value="Daily check-in. Earns Yuan + score on every shared server. Streak builds up to ¥2,000/day.", inline=False)
        return e

    def _page_economy(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · ECONOMY")
        e.add_field(
            name="EARNING YUAN",
            value=(
                f"¥10 per message · [Support server]({SUPPORT_URL}) members earn +15% globally\n"
                "After 25 yuan-earning messages/day, further messages pay 25% · Resets at midnight UTC\n"
                "**Wealth tax:** balance ≥ ¥100,000 → 10% of every credit goes to the Bureau Treasury"
            ),
            inline=False,
        )
        e.add_field(name="/yuan",                           value="Balance, lifetime earned, and lifetime spent.", inline=False)
        e.add_field(name="/transfer <citizen> <amount>",    value="Send Yuan directly. Confirmation prompt before executing.", inline=False)
        e.add_field(name="/requestyuan <citizen> <amount>", value="Request Yuan from another citizen. They Accept or Decline. Expires in 5 min.", inline=False)
        e.add_field(name="/battle <opponent> <amount>",     value="50/50 Yuan duel. Min ¥1,000. Both risk the same amount. Winner takes all. Opponent must Accept within 5 min.", inline=False)
        e.add_field(name="/confess <text>",                 value="Public confession. Costs ¥200–¥750 scaled to score deficit. Grants +0.5 score. 1-hour cooldown.", inline=False)
        e.add_field(
            name="/vote",
            value=(
                "Vote on Top.gg. Earns the **Loyal Patriot** badge, +2.00 score, and ¥1,500+ on every shared server. "
                "Scales with vote streak, weekend bonus, and lucky roll. Lasts 12 hours — vote again to renew."
            ),
            inline=False,
        )
        return e

    def _page_shop(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · SHOP & ITEMS")
        e.add_field(name="/shop",  value="Browse all items across 5 categories: **Core** · **Economy** · **Misc** · **Lottery** · **Cosmetic**.", inline=False)
        e.add_field(
            name="KEY ITEMS  ·  /buy <item_id> [target]",
            value=(
                "`report` ¥2,500 · Dock target 2 score\n"
                "`denounce` ¥12,000 · Dock target 20 score · 48h cooldown per target\n"
                "`rehabilitate` ¥3,000+ · +3 score, cost doubles each use\n"
                "`appeal` ¥4,000 · Next penalty halved (12h)\n"
                "`exception` ¥12,000 · Block the next negative action against you\n"
                "`reeducation` ¥20,000 · Freeze a target's score for 2h\n"
                "`surveillance` ¥2,000 · Unlock one `/surveillance_report` use on a target"
            ),
            inline=False,
        )
        e.add_field(
            name="LOTTERY TIERS",
            value=(
                "All: 70% lose · 20% win · 10% jackpot. Add `target` to buy for someone else.\n"
                "`lottery` ¥500 · `lottery_standard` ¥2,500 · `lottery_premium` ¥10,000\n"
                "`lottery_elite` ¥50,000 · `lottery_chairman` ¥250,000"
            ),
            inline=False,
        )
        e.add_field(name="GIFTING", value="Add a `target` to any self-item (`rehabilitate`, `appeal`, `exception`, etc.) to gift it publicly. Add `text` for a message.", inline=False)
        e.add_field(name="/surveillance_report <target>", value="Redeem a surveillance package. Shows a full 30-day dossier: score trend, yuan, all-time high/low, threat assessment.", inline=False)
        return e

    def _page_social(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · SOCIAL RATING")
        e.add_field(name="/endorse <citizen> [reason]", value="Grant **+1.5 score**. One use per citizen per 24 hours. Reason is public.", inline=False)
        e.add_field(name="/rebuke <citizen> [reason]",  value="Apply **-1.5 score**. One use per citizen per 24 hours. Reason is public.", inline=False)
        e.add_field(
            name="FUNDRAISERS",
            value=(
                "`/fundraise create <goal> <desc>` · Start a fundraiser with a Yuan goal\n"
                "`/fundraise donate <id> <amount>` · Donate yuan (held in escrow)\n"
                "`/fundraise complete <id>` · Mark yours as complete, opening the vote phase\n"
                "`/fundraise vote <id> <confirm|deny>` · Vote on whether the organizer followed through\n"
                "`/fundraise list` · Active fundraisers · `/fundraise info <id>` · Full details"
            ),
            inline=False,
        )
        return e

    def _page_markets(self) -> discord.Embed:
        hours_lines = []
        for exchange, st in self._exchange_status.items():
            tag = "Open" if st["open"] else "Closed"
            event_lbl = "Closes" if st["next_event"] == "close" else "Opens"
            hours_lines.append(f"**{_EXCHANGE_NAMES[exchange]}** ({exchange}) · {tag} · {event_lbl} <t:{st['next_ts']}:R>")

        e = discord.Embed(color=0xCC0000, title="北京证券交易所 · MARKETS")
        e.add_field(name="MARKET STATUS", value="\n".join(hours_lines), inline=False)
        e.add_field(
            name="STOCKS",
            value=(
                "5 China ADRs (NYSE) · 3 LSE blue chips · 3 TSE blue chips · 1 ETF (CNXF) · 5 Penny stocks\n"
                "All prices in Yuan. Buy/sell blocked when exchange is closed.\n"
                "Holding stocks at 2%+ unrealized gain boosts score up to +0.30/day."
            ),
            inline=False,
        )
        e.add_field(
            name="STOCK COMMANDS",
            value=(
                "`/market` · Live prices for all tickers\n"
                "`/stocks chart <ticker> [period]` · Price chart (1D 5D 1M 3M 6M 1Y)\n"
                "`/stocks buy <ticker> <shares>` · Buy shares\n"
                "`/stocks sell <ticker> <shares>` · Sell shares\n"
                "`/stocks portfolio` · Open positions with live P&L"
            ),
            inline=False,
        )
        e.add_field(
            name="TURBO CERTIFICATES",
            value=(
                "12 turbos generated daily. Leveraged long/short with a knockout barrier.\n"
                "Leverage: 2x 3x 5x 7x 10x — knocked out if price crosses the barrier.\n"
                "`/turbos list` · Today's turbos · `/turbos open <id> <yuan>` · `/turbos close <pos_id>`"
            ),
            inline=False,
        )
        e.add_field(name="CIRCUIT BREAKERS", value="7% intraday move → 15-min halt · 20% daily move → locked for the day.", inline=False)
        return e

    def _page_events(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · EVENTS & POSTERS")
        e.add_field(name="ccp poster",         value="Display a random propaganda poster. Available to all citizens.", inline=False)
        e.add_field(name="DAILY BROADCASTS",   value="Enabled by a mod. A new poster is broadcast daily. React ❤️ → +3 score and ¥250 · React 😡 → -1 score.", inline=False)
        e.add_field(
            name="PROPAGANDA EVENTS",
            value=(
                "1. Mod opens a submission event with `/propaganda start`\n"
                "2. Citizens submit quotes via `/propaganda submit <text>` (max 280 chars)\n"
                "3. After the deadline, all submissions are posted with 👍/👎 reaction voting\n"
                "4. Most-approved quote becomes an official guild decree, retrievable via `/decree`"
            ),
            inline=False,
        )
        e.add_field(name="BANNED CONTENT", value="Submissions referencing banned topics: **−5.00 score** and a ban from that event.", inline=False)
        return e

    def _page_achievements(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="成就 · ACHIEVEMENTS")
        e.add_field(name="/achievements [citizen]", value="View all unlocked and locked achievements. Secret ones show only a hint until earned.", inline=False)
        e.add_field(name="CATEGORIES",             value="Score · Economy · Social · Markets · Propaganda · Joke", inline=False)
        e.add_field(name="REWARDS",                value="Most achievements grant Yuan, score, or a cosmetic badge shown in your profile header.", inline=False)
        e.add_field(name="RARITY",                 value="Each achievement shows the percentage of citizens who have unlocked it.", inline=False)
        e.add_field(name="MOD SETTINGS",           value="`ccp achievementnotification [on|off]` · `ccp achievementchannel [#channel]`", inline=False)
        return e

    def _page_mod(self) -> discord.Embed:
        e = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · MOD COMMANDS")
        e.description = "Prefix commands typed directly in chat. Requires **Manage Server** permission."
        e.add_field(
            name="CITIZEN MANAGEMENT",
            value=(
                "`ccp initialize` · Register all current members\n"
                "`ccp adjust <@citizen> <delta> <reason>` · Manual score adjustment\n"
                "`ccp reset <@citizen>` · Reset score to 750"
            ),
            inline=False,
        )
        e.add_field(
            name="SERVER SETTINGS",
            value=(
                "`ccp threshold <n>` · Fundraiser vote threshold (default 3)\n"
                "`ccp executions [#channel]` · Dedicated execution notice channel\n"
                "`ccp roles [on|off]` · Toggle rank role assignment"
            ),
            inline=False,
        )
        e.add_field(
            name="ACHIEVEMENTS & POSTERS",
            value=(
                "`ccp achievementnotification [on|off]` · Toggle unlock announcements\n"
                "`ccp achievementchannel [#channel]` · Dedicated achievement channel\n"
                "`ccp posters [on|off]` · Toggle daily poster broadcast in this channel\n"
                "`ccp posterschannel [#channel]` · Set dedicated poster channel"
            ),
            inline=False,
        )
        e.add_field(
            name="/propaganda start <submit_ch> <reveal_ch> <hours>",
            value="Open a propaganda submission event. Citizens submit quotes, voting runs 24h, winner becomes a guild decree.",
            inline=False,
        )
        return e

    def _page_privacy(self) -> discord.Embed:
        e = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · PRIVACY & LEGAL")
        e.add_field(
            name="/optout",
            value=(
                "Permanently opt out of the Social Credit System. Stops message scoring and blocks all commands. "
                "Permanently deletes all data tied to your Discord ID across every server: score, yuan, history, achievements, "
                "badges, portfolios, and more. Requires confirmation."
            ),
            inline=False,
        )
        e.add_field(
            name="/optin",
            value="Reverse an opt-out. Re-registers you as a brand new citizen starting from scratch. Requires confirmation.",
            inline=False,
        )
        e.add_field(
            name="DISCLAIMER",
            value=(
                "This bot is a satirical meme project, not affiliated with or representative of the CCP or Chinese government. "
                "The creator does not endorse authoritarianism or surveillance. This is a joke. The irony is the point. "
                "Run `/disclaimer` for full text."
            ),
            inline=False,
        )
        return e


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

    def _make_guide_view(self) -> tuple[GuideView, discord.Embed]:
        view = GuideView(_all_exchange_status())
        return view, view.build("overview")

    @app_commands.command(name="guide", description="Full guide to the Social Credit System")
    async def guide(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view, embed = self._make_guide_view()
        await interaction.followup.send(embed=embed, view=view, file=discord.File("images/bureau.png"), ephemeral=True)

    @app_commands.command(name="help", description="Full guide to the Social Credit System")
    async def help(self, interaction: discord.Interaction):
        await self.guide.callback(self, interaction)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        try:
            await ctx.message.add_reaction("🇨🇳")
        except discord.HTTPException:
            pass
        view, embed = self._make_guide_view()
        await ctx.reply(embed=embed, view=view, file=discord.File("images/bureau.png"))

    @app_commands.command(name="ping", description="Check the Bureau's response latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · SIGNAL CHECK",
            description=f"The Bureau responds in **{latency_ms} ms**. Your transmission has been logged.",
        )
        e.set_thumbnail(url="attachment://bureau.png")
        await interaction.response.send_message(embed=e, file=discord.File("images/bureau.png"), ephemeral=True)

    @app_commands.command(name="decree", description="Receive an official proclamation from the Bureau")
    async def decree(self, interaction: discord.Interaction):
        if random.random() < 0.15:
            treasury_total = await self.bot.db.get_treasury_total()
            description = f"*The Bureau Treasury holds ¥{treasury_total:,} in seized assets, awaiting redistribution to the deserving.*"
        else:
            guild_decrees = await self.bot.db.get_guild_decrees(interaction.guild.id, limit=10)
            guild_pool = [d["content"] for d in guild_decrees] if guild_decrees else []
            xi_pool = self._quotes or FALLBACK_DECREES
            pool = guild_pool + xi_pool
            description = f"*{random.choice(pool)}*"
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · OFFICIAL DECREE",
            description=description,
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="credits", description="Open-source libraries powering the Bureau")
    async def credits(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · ACKNOWLEDGEMENTS",
            description="The surveillance apparatus is built on the following open-source technologies. The Party is grateful.",
        )
        e.set_thumbnail(url="attachment://bureau.png")
        for name, desc in CREDITS_LINES:
            e.add_field(name=name, value=desc, inline=False)
        e.add_field(name="SOURCE CODE", value=f"[GitHub]({REPO_URL})", inline=False)
        await interaction.response.send_message(embed=e, file=discord.File("images/bureau.png"), ephemeral=True)

    @app_commands.command(name="disclaimer", description="Legal and ethical disclaimer for this bot")
    async def disclaimer(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · DISCLAIMER",
            description=(
                "This bot is a **satirical meme project** and is not affiliated with, endorsed by, "
                "or representative of the Chinese Communist Party or the Chinese government.\n\n"
                "The creator does not support, condone, or endorse the human rights abuses, "
                "authoritarian policies, or surveillance practices of the CCP, including but not "
                "limited to the treatment of Uyghurs, Tibetans, Hong Kongers, and political dissidents, "
                "the Tiananmen Square massacre, or real-world social credit systems.\n\n"
                "This is a joke. The irony is the point."
            ),
        )
        e.set_thumbnail(url="attachment://bureau.png")
        await interaction.response.send_message(embed=e, file=discord.File("images/bureau.png"))

    @app_commands.command(name="invite", description="Invite the Bureau to expand to another server")
    async def invite(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · EXPAND THE BUREAU",
            description="Bring social credit surveillance to your own server. Compliance is mandatory. Resistance is futile.",
        )
        e.set_thumbnail(url="attachment://bureau.png")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Add to Server", style=discord.ButtonStyle.link, url=TOPGG_URL))
        view.add_item(discord.ui.Button(label="Support Server", style=discord.ButtonStyle.link, url=SUPPORT_URL))
        await interaction.response.send_message(embed=e, file=discord.File("images/bureau.png"), view=view)

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
        e.set_thumbnail(url="attachment://bureau.png")
        await interaction.followup.send(embed=e, file=discord.File("images/bureau.png"), ephemeral=True)

    @app_commands.command(name="botinfo", description="Information about Social Credit Surveillantr")
    async def botinfo(self, interaction: discord.Interaction):
        await interaction.response.defer()

        guild_count  = len(self.bot.guilds)
        member_count = sum(g.member_count or 0 for g in self.bot.guilds)
        discord_ms   = round(self.bot.latency * 1000)

        t0 = time.time()
        stats = await self.bot.db.get_global_stats()
        db_ms = round((time.time() - t0) * 1000, 1)

        e = discord.Embed(
            color=0xCC0000,
            title="中华人民共和国社会信用局 · BOT INFORMATION",
            description=(
                "An authoritative CCP-themed social credit system for Discord. "
                "Every citizen is monitored. Every message is evaluated. Glory awaits the compliant."
            ),
        )
        e.set_thumbnail(url="attachment://bureau.png")
        e.add_field(name="VERSION",  value="1.0.3",   inline=True)
        e.add_field(name="CREATOR",  value="OFF-BY-ONE (saguny & digitalwarpstar)",  inline=True)
        e.add_field(name="LATENCY",  value=f"{discord_ms} ms discord · {db_ms} ms database", inline=True)
        e.add_field(
            name="GLOBAL STATISTICS",
            value=(
                f"**Servers · Citizens** · {guild_count} servers · {member_count:,} citizens\n"
                f"**Yuan in Circulation** · ¥{stats['total_yuan']:,}\n"
                f"**Bureau Treasury** · ¥{stats['treasury_total']:,}\n"
                f"**Messages Rated** · {stats['total_messages']:,}\n"
                f"**Highest · Lowest Score** · {stats['highest_score']:.2f} · {stats['lowest_score']:.2f}"
            ),
            inline=False,
        )
        e.add_field(name="TECHNOLOGY", value="discord.py 2.x · PostgreSQL · vaderSentiment · langdetect · deep-translate", inline=False)
        e.add_field(name="LINKS",      value=f"[Source Code]({REPO_URL}) · [Invite to Server]({INVITE_URL}) · [Public Dashboard]({DASHBOARD_URL})", inline=False)
        e.add_field(
            name="★ SUPPORT SERVER ★",
            value=f"[Join here]({SUPPORT_URL}) · changelogs and updates posted constantly, this is the place to follow.\nAlso join for a +15% yuan boost globally!",
            inline=False,
        )
        e.set_footer(text="Disclaimer: see /disclaimer")
        await interaction.followup.send(embed=e, file=discord.File("images/bureau.png"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
