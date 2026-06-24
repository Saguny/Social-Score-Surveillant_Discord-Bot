import re
import random
import time
from datetime import datetime, timezone, timedelta
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

    def _build_guide_batches(self) -> list[list[discord.Embed]]:
        embeds = []

        e0 = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · DATA AND PRIVACY")
        e0.description = "Before anything else, citizens should know their rights regarding personal data."
        e0.add_field(
            name="/optout",
            value=(
                "Permanently opt out of the Social Credit System. This immediately stops your messages "
                "from being scored and blocks you from using any other bot command. Every row of data tied "
                "to your Discord ID is permanently deleted across every server the Bureau operates in: "
                "score, yuan, transaction history, achievements, badges, fundraiser activity, stock "
                "portfolios, vote history, and everything else. Requires confirmation before it takes effect."
            ),
            inline=False,
        )
        e0.add_field(
            name="/optin",
            value=(
                "Reverses an opt-out. Since opting out permanently deletes your data, opting back in "
                "re-registers you as a brand new citizen starting from scratch. Requires confirmation."
            ),
            inline=False,
        )
        e0.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e0)

        e1 = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · SCORING RULES")
        e1.description = (
            "Every message you send is evaluated by the Bureau. "
            "Score changes are silent and accumulate over time. The Bureau will notify you when something significant happens."
        )
        e1.add_field(
            name="SENTIMENT",
            value=(
                "Each message is analyzed for tone. Positive messages nudge your score up, "
                "negative ones nudge it down. Max impact per message is +0.30 or -0.30. "
                "Neutral messages grant a small +0.03 bonus for civic participation.\n"
                "Consecutive positive messages build a streak multiplier (up to 1.5x at streak 15+)."
            ),
            inline=False,
        )
        e1.add_field(
            name="DAILY MESSAGE LIMITS",
            value=(
                "Score gains from messages are capped at **+8.00 net per day**. "
                "Once reached, further positive messages yield nothing until penalties bring you below the cap.\n"
                "Once your net score gained today reaches **+6.00**, further positive messages contribute at 25% effectiveness. "
                "This reverses automatically if penalties bring your net back below +6.00 — it is not a one-way switch.\n"
                "Negative penalties are always full strength regardless of net score today."
            ),
            inline=False,
        )
        e1.add_field(
            name="COUNTER-REVOLUTIONARY SPEECH",
            value=(
                "Messages referencing banned topics (Tiananmen, Taiwan independence, Xinjiang, Tibet, "
                "Falun Gong, and related subjects) are flagged regardless of tone. Penalty: -0.30."
            ),
            inline=False,
        )
        e1.add_field(
            name="STRUCTURAL VIOLATIONS",
            value=(
                "Sending the same message twice in a row (10+ characters): -0.7\n"
                "Excessive caps (16+ character messages, 80%+ uppercase): -0.4"
            ),
            inline=False,
        )
        e1.add_field(
            name="INACTIVITY DECAY",
            value="Citizens inactive for more than 7 days will have their score gently nudged toward 750 each day until they return.",
            inline=False,
        )
        e1.set_footer(text="Disclaimer: see /disclaimer · GLORY TO THE CCP!")
        embeds.append(e1)

        e2 = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CITIZEN GUIDE")
        e2.description = (
            "Score range: 600 (floor) to 1300 (ceiling). Everyone starts at 750. "
            "Rank changes trigger an official bureau notification."
        )
        rank_lines = "\n".join(f"{r['min']} to {r['max']}   {r['name']}" for r in RANKS)
        e2.add_field(name="RANKS", value=f"```\n{rank_lines}\n```", inline=False)
        e2.add_field(
            name="EXECUTION LIST",
            value=(
                "Citizens whose score falls to 610 or below are placed on the Execution List "
                "and assigned the role **Execution Date: Tomorrow**. Their Yuan balance is confiscated and distributed to other citizens. "
                "Check your score regularly with `/score` — recovery above 610 removes the role."
            ),
            inline=False,
        )
        e2.add_field(
            name="RANK CHANGE REWARDS",
            value=(
                "Promotions award Yuan based on the rank you enter. Demotions deduct Yuan based on the rank you leave. "
                "Amounts scale with rank tier. Higher tiers carry larger rewards and steeper penalties."
            ),
            inline=False,
        )
        e2.add_field(
            name="RANK ROLES",
            value=(
                "By default the bot automatically creates and assigns a Discord server role for each rank tier, "
                "keeping it in sync with your score. Mods can disable this with `ccp roles off` if the server "
                "does not want role clutter. The Execution List role is always active regardless of this setting."
            ),
            inline=False,
        )
        embeds.append(e2)

        e3 = discord.Embed(color=0xCC0000, title="SCORE AND STAT COMMANDS")
        e3.add_field(name="/score [citizen]",        value="View your score and current rank.", inline=False)
        e3.add_field(name="/stats [citizen]",        value="Full breakdown across 3 pages: Overview (score, rank, trends, rank streak · total days at rank), Social (endorsements, rebukes, reports), Economy (yuan, items, lottery stats, check-in streak).", inline=False)
        e3.add_field(name="/daily_report [citizen]",  value="Today's score activity for any citizen: positive, negative, net change, message counts (positive/negative/neutral), and yuan compared to yesterday.", inline=False)
        e3.add_field(name="/leaderboard",            value="Rankings across 5 pages: Score, Economy, Activity, Social, and Markets (portfolio value and realized P&L).", inline=False)
        e3.add_field(name="/state_report",           value="Server-wide report: biggest rise/fall, top informant, yuan in circulation, avg score.", inline=False)
        e3.add_field(name="/graph <score|yuan> [citizen]", value="Generate a 30-day trend graph for score or yuan. Yuan graph populates once per day.", inline=False)
        e3.add_field(name="/checkin",                value="Perform your daily check-in. Earns Yuan and a small score bump on every server you share with the bot. Streak increases daily reward up to ¥2,000.", inline=False)
        e3.add_field(name="/botinfo",                value="Technical information about the bot: creator, tech stack, server count, repo and invite links.", inline=False)
        e3.add_field(name="/uptime",                 value="How long the Bureau has been active since last restart.", inline=False)
        e3.add_field(name="/ping",                   value="Check the Bureau's response latency.", inline=False)
        e3.add_field(name="/decree",                 value="Receive an official proclamation from the Bureau. May include decrees written by citizens.", inline=False)
        e3.add_field(name="/credits",                value="Open-source libraries powering the surveillance apparatus.", inline=False)
        e3.add_field(name="/invite",                 value="Get a link to expand the Bureau's reach to another server.", inline=False)
        embeds.append(e3)

        e4 = discord.Embed(color=0xCC0000, title="YUAN AND ECONOMY")
        e4.add_field(
            name="Earning Yuan",
            value=(
                "You earn ¥10 per message automatically. Check-ins and propaganda victories are additional sources.\n"
                f"Members of the [support server]({SUPPORT_URL}) earn +15% Yuan per message, checked live, leave and it switches off."
            ),
            inline=False,
        )
        e4.add_field(name="/yuan",         value="Check your Yuan balance and lifetime earned/spent.", inline=False)
        e4.add_field(name="/transfer <citizen> <amount>", value="Send Yuan directly to another citizen. A confirmation prompt shows the amount and your balance after transfer before executing.", inline=False)
        e4.add_field(name="/requestyuan <citizen> <amount>", value="Request Yuan from another citizen. Posts a public embed they can Accept or Decline. Expires after 5 minutes.", inline=False)
        e4.add_field(name="/battle <opponent> <amount>", value="Challenge a citizen to a 50/50 Yuan duel. Minimum ¥1,000 stake. Both sides risk the same amount, the opponent must Accept or Decline within 5 minutes, and the winner takes both stakes. Declining or letting it expire refunds the challenger in full.", inline=False)
        e4.add_field(
            name="/shop",
            value=(
                "Browse the full catalogue across 5 categories. Run `/shop` first to see what you can afford at your current balance.\n"
                "Categories: **Core** (reports, defense, rehabilitation) · **Economy** (bounties, disputes) · "
                "**Misc** (inspection, legal cover, fabricated evidence) · **Lottery** (5 tiers) · **Cosmetic** (prestige badges, Winnie the Pooh)"
            ),
            inline=False,
        )
        e4.add_field(
            name="/buy <item> [target] [text]",
            value=(
                "Purchase any item by its ID. Key items:\n"
                "`report` (¥2,500) · Dock a target 2 score points.\n"
                "`denounce` (¥12,000) · Public denouncement. Docks target 20 score points. 48h cooldown per target.\n"
                "`surveillance` (¥2,000) · Unlocks one `/surveillance_report` use on a target.\n"
                "`rehabilitate` (¥3,000+) · Recover +3 score. Cost doubles each use.\n"
                "`appeal` (¥4,000) · Next incoming penalty reduced 50% within 12 hours.\n"
                "`exception` (¥12,000) · Completely cancels the next negative action against you.\n"
                "`reeducation` (¥20,000) · Freeze a target's score for 2 hours.\n"
                "**Gifting:** Add a `target` to any self-item (`rehabilitate`, `appeal`, `exception`, `model_citizen`, `legal_rep`, `immunity`, `media_coverage`) "
                "to gift it to another citizen instead. A public announcement is posted. Add `text` as a gift message.\n"
                "See `/shop` for all items."
            ),
            inline=False,
        )
        e4.add_field(
            name="LOTTERY TIERS",
            value=(
                "Five tiers scaling with your wealth. All share the same 70/20/10 odds. Add a `target` to buy a ticket for someone else.\n"
                "`lottery` ¥500 · win ¥600–1,000 · jackpot ¥2,000–4,000\n"
                "`lottery_standard` ¥2,500 · win ¥3,000–5,000 · jackpot ¥10,000–20,000\n"
                "`lottery_premium` ¥10,000 · win ¥12,000–18,000 · jackpot ¥40,000–80,000\n"
                "`lottery_elite` ¥50,000 · win ¥60,000–90,000 · jackpot ¥200,000–400,000\n"
                "`lottery_chairman` ¥250,000 · win ¥300,000–500,000 · jackpot ¥1,000,000–2,000,000"
            ),
            inline=False,
        )
        e4.add_field(
            name="/surveillance_report <target>",
            value="Redeem a purchased surveillance package. Shows a full 30-day intelligence dossier: score trend, yuan, all-time high/low, threat assessment, and top activity breakdown.",
            inline=False,
        )
        e4.add_field(
            name="/confess <text>",
            value=(
                "Publicly confess your crimes to the Bureau. Costs Yuan scaled to how far your score has fallen "
                "(¥200 minimum · up to ¥750 at the floor). Grants +0.5 score on acceptance. 1 hour cooldown."
            ),
            inline=False,
        )
        e4.add_field(
            name="/vote",
            value=(
                "Vote for this bot on Top.gg. Earns the Loyal Patriot badge, +2.00 score, and ¥1,500 yuan "
                "on every server you share with the bureau. Lasts 12 hours · vote again to renew."
            ),
            inline=False,
        )
        embeds.append(e4)

        e5 = discord.Embed(color=0xCC0000, title="SOCIAL RATING")
        e5.add_field(
            name="/endorse <citizen> [reason]",
            value="Grant a citizen a positive rating. Adjusts their score by +1.5. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.add_field(
            name="/rebuke <citizen> [reason]",
            value="Issue a negative rating against a citizen. Adjusts their score by -1.5. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e5)

        e6 = discord.Embed(color=0xCC0000, title="FUNDRAISERS")
        e6.add_field(
            name="LIFECYCLE",
            value=(
                "1. Organizer creates a fundraiser with a Yuan goal and a description of what they will do.\n"
                "2. Citizens donate Yuan. Donated funds are held in escrow.\n"
                "3. When the goal is reached, the organizer must follow through, then mark it complete.\n"
                "4. Citizens vote to confirm or deny. If enough confirm, the organizer receives the funds. "
                "If enough deny, all donors are refunded."
            ),
            inline=False,
        )
        e6.add_field(name="/fundraise create <goal> <description>", value="Start a fundraiser. Set a Yuan goal and describe what you will do.", inline=False)
        e6.add_field(name="/fundraise donate <id> <amount>",        value="Donate Yuan to an open fundraiser. Cannot donate to your own.", inline=False)
        e6.add_field(name="/fundraise complete <id>",               value="Mark your funded fundraiser as complete. Opens the voting phase.", inline=False)
        e6.add_field(name="/fundraise vote <id> <confirm|deny>",    value="Vote on whether the organizer fulfilled their obligation. One vote per citizen.", inline=False)
        e6.add_field(name="/fundraise list",                        value="List all active fundraisers in this server.", inline=False)
        e6.add_field(name="/fundraise info <id>",                   value="View full details and vote tally for a specific fundraiser.", inline=False)
        embeds.append(e6)

        e7 = discord.Embed(color=0x333333, title="MOD COMMANDS")
        e7.description = "Prefix commands are typed directly in chat. Slash commands marked with / require mod permissions."
        e7.add_field(name="ccp initialize",                         value="Register all current server members into the system.", inline=False)
        e7.add_field(name="ccp adjust <@citizen> <delta> <reason>", value="Manually adjust a citizen's score by any amount.", inline=False)
        e7.add_field(name="ccp reset <@citizen>",                   value="Reset a citizen back to 750.", inline=False)
        e7.add_field(name="ccp threshold <n>",                      value="Set how many votes are required to resolve a fundraiser. Default is 3.", inline=False)
        e7.add_field(name="ccp executions [#channel]",              value="Set a dedicated channel for Execution List notices. Omit the channel to clear and revert to posting in the message channel.", inline=False)
        e7.add_field(name="ccp roles [on|off]",                     value="Toggle whether rank tier changes assign real Discord server roles. On by default. Execution List role is unaffected.", inline=False)
        e7.add_field(name="ccp achievementnotification [on|off]",   value="Toggle public channel announcements when a citizen unlocks an achievement. On by default.", inline=False)
        e7.add_field(name="ccp achievementchannel [#channel]",      value="Set a dedicated channel for achievement unlock announcements. Omit the channel to clear and revert to posting in the triggering channel.", inline=False)
        e7.add_field(name="ccp posters [on|off]",                    value="Toggle daily propaganda poster broadcasts in this channel. Omit the argument to toggle.", inline=False)
        e7.add_field(name="ccp posterschannel [#channel]",           value="Set a dedicated channel for daily poster broadcasts. Omit the channel to use the current one.", inline=False)
        e7.add_field(
            name="/propaganda start <submit_channel> <reveal_channel> <duration_hours>",
            value=(
                "Open a propaganda submission event. Citizens submit quotes via `/propaganda submit`. "
                "When the submission window closes, all entries are posted in the reveal channel with reaction voting. "
                "After 24 hours, the winning quote is enshrined as an official guild decree."
            ),
            inline=False,
        )
        e7.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e7)

        exchange_status = _all_exchange_status()
        hours_lines = []
        for exchange, st in exchange_status.items():
            tag = "🟢 Open now" if st["open"] else "🔴 Closed now"
            event_lbl = "Closes" if st["next_event"] == "close" else "Opens"
            hours_lines.append(f"**{_EXCHANGE_NAMES[exchange]}** ({exchange})  {tag} · {event_lbl} <t:{st['next_ts']}:R>")

        e_stocks = discord.Embed(color=0xCC0000, title="北京证券交易所 · MARKETS")
        e_stocks.add_field(
            name="MARKET HOURS",
            value=(
                "\n".join(hours_lines) + "\n"
                "TSE observes a midday lunch recess (11:30–12:30 JST) where trading pauses.\n"
                "When an exchange is closed, its tickers freeze at the last traded price — "
                "charts and portfolio history hold a flat line until that exchange reopens, "
                "exactly like a real broker."
            ),
            inline=False,
        )
        e_stocks.add_field(
            name="STOCKS · PRICES SHOWN IN YUAN",
            value=(
                "New York · 5 China ADRs (BABA, BIDU, NIO, JD, BILI) · real prices via yfinance\n"
                "London · 3 LSE blue chips (HSBA.L, BP.L, ULVR.L) · GBX converted to GBP then Yuan\n"
                "Tokyo · 3 TSE blue chips (7203.T Toyota, 6758.T Sony, 9984.T SoftBank) · JPY to Yuan\n"
                "1 ETF (CNXF) · tracks the basket average of all 11 real tickers across all 3 exchanges\n"
                "5 Penny stocks (XMNG, DWJT, HQBC, RMKD, WSJZ) · high-volatility simulation, NYSE hours\n"
                "Penny stocks may trigger a 🔥 PUMP · sudden drift followed by a -20% crash\n"
                "All non-Yuan prices are converted live using USD/GBP/JPY to Yuan exchange rates."
            ),
            inline=False,
        )
        e_stocks.add_field(
            name="SOCIAL CREDIT BONUS",
            value=(
                "Holding stocks at a 2%+ unrealized gain slowly raises your score. "
                "Checked once every 24 hours alongside score decay. "
                "Reward scales with your gain percentage, capped at +0.30 per day. Losses never penalize score."
            ),
            inline=False,
        )
        e_stocks.add_field(name="/market",           value="Live prices for all stocks with market status, opening hours, and day-open prices.", inline=False)
        e_stocks.add_field(
            name="/stocks chart <ticker> [period] [candlestick|line]",
            value="Price chart for any stock. Periods: 1D · 5D · 1M · 3M · 6M · 1Y.",
            inline=False,
        )
        e_stocks.add_field(name="/stocks buy <ticker> <shares>",   value="Buy shares. Deducted from your Yuan balance.", inline=False)
        e_stocks.add_field(name="/stocks sell <ticker> <shares>",  value="Sell shares. Proceeds added to Yuan. P&L tracked.", inline=False)
        e_stocks.add_field(name="/stocks portfolio",               value="View all open stock positions and turbo certificates with live P&L.", inline=False)
        e_stocks.add_field(
            name="TURBO CERTIFICATES",
            value=(
                "12 turbos generated daily across all tickers. Each is a leveraged directional instrument.\n"
                "**LONG** · profits if price rises · **SHORT** · profits if price falls\n"
                "Leverage: 2x 3x 5x 7x 10x · Knockout: price level that wipes the position\n"
                "A 10x Long is knocked out at -10% · a 5x Short is knocked out at +20%"
            ),
            inline=False,
        )
        e_stocks.add_field(name="/turbos list",                    value="View today's 12 turbos with knockout levels and current value factor.", inline=False)
        e_stocks.add_field(name="/turbos open <id> <yuan>",        value=f"Invest yuan in a turbo. Minimum ¥100. Value updates every 2 minutes.", inline=False)
        e_stocks.add_field(name="/turbos close <position_id>",     value="Manually close a turbo position and collect proceeds.", inline=False)
        e_stocks.add_field(
            name="CIRCUIT BREAKERS",
            value="7% intraday move halts trading 15 min · 20% daily move locks the stock for the day.",
            inline=False,
        )
        embeds.append(e_stocks)

        e8 = discord.Embed(color=0xCC0000, title="PROPAGANDA EVENTS")
        e8.add_field(name="ccp poster", value="Display a random propaganda poster. Available to all citizens.", inline=False)
        e8.add_field(
            name="DAILY PROPAGANDA BROADCASTS",
            value="When enabled by a mod, a poster is posted daily. React ❤️ for +3 score and ¥250 · React 😡 for -1 score.",
            inline=False,
        )
        e8.add_field(
            name="/propaganda submit <text>",
            value=(
                "Submit your propaganda quote to the active event (max 280 characters). One submission per citizen per event. "
                "Submissions containing banned content result in a −5.00 score penalty and a ban from that event."
            ),
            inline=False,
        )
        e8.add_field(
            name="EVENT LIFECYCLE",
            value=(
                "1. Mod starts event with a submission channel and reveal channel.\n"
                "2. Citizens submit via `/propaganda submit` before the deadline.\n"
                "3. On close, all submissions are posted in the reveal channel with 👍/👎 reactions.\n"
                "4. After 24 hours, the most-approved submission becomes an official guild decree, "
                "accessible via `/decree`. The winner's profile records a Propaganda Victory."
            ),
            inline=False,
        )
        e8.set_footer(text="Disclaimer: see /disclaimer · GLORY TO THE CCP!")
        embeds.append(e8)

        e9 = discord.Embed(color=0xCC0000, title="成就 · ACHIEVEMENTS")
        e9.add_field(
            name="/achievements [citizen]",
            value="View your unlocked and locked achievements. Locked secret achievements show only a hint until earned.",
            inline=False,
        )
        e9.add_field(
            name="CATEGORIES",
            value="Score · Economy · Social · Markets · Propaganda · Joke",
            inline=False,
        )
        e9.add_field(
            name="For Mods",
            value=(
                "Turn off by using `ccp achievementnotification off`, choose a channel by doing `ccp achievementchannel [channel]"
            ),
            inline=False,
        )
        e9.add_field(
            name="REWARDS",
            value="Most achievements grant Yuan, score, or a cosmetic badge shown in your profile header.",
            inline=False,
        )
        e9.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e9)

        return [
            embeds[0:1],
            embeds[1:3],
            embeds[3:5],
            embeds[5:8],
            embeds[8:10],
            embeds[10:11],
        ]

    @app_commands.command(name="guide", description="Full guide to the Social Credit System")
    async def guide(self, interaction: discord.Interaction):
        batches = self._build_guide_batches()
        await interaction.response.defer(ephemeral=True)
        try:
            for batch in batches:
                await interaction.user.send(embeds=batch)
            await interaction.followup.send("The Bureau's orientation package has been dispatched to your private channel.", ephemeral=True)
        except discord.Forbidden:
            for batch in batches:
                await interaction.followup.send(embeds=batch, ephemeral=True)

    @app_commands.command(name="help", description="Full guide to the Social Credit System")
    async def help(self, interaction: discord.Interaction):
        await self.guide.callback(self, interaction)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        try:
            await ctx.message.add_reaction("🇨🇳")
        except discord.HTTPException:
            pass
        batches = self._build_guide_batches()
        try:
            for batch in batches:
                await ctx.author.send(embeds=batch)
        except discord.Forbidden:
            await ctx.send("Your DMs are closed. Run `/help` or `/guide` instead.")

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
        guild_decrees = await self.bot.db.get_guild_decrees(interaction.guild.id, limit=10)
        guild_pool = [d["content"] for d in guild_decrees] if guild_decrees else []
        xi_pool = self._quotes or FALLBACK_DECREES
        pool = guild_pool + xi_pool
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
        e.set_thumbnail(url="attachment://bureau.png")
        for name, desc in CREDITS_LINES:
            e.add_field(name=name, value=desc, inline=False)
        e.add_field(
            name="SOURCE CODE",
            value=f"[GitHub]({REPO_URL})",
            inline=False,
        )
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
        e.add_field(name="CREATOR",  value="saguny",  inline=True)
        e.add_field(name="LATENCY",  value=f"{discord_ms} ms discord · {db_ms} ms database", inline=True)
        e.add_field(
            name="GLOBAL STATISTICS",
            value=(
                f"**Servers · Citizens** · {guild_count} servers · {member_count:,} citizens\n"
                f"**Yuan in Circulation** · ¥{stats['total_yuan']:,}\n"
                f"**Messages Rated** · {stats['total_messages']:,}\n"
                f"**Highest · Lowest Score** · {stats['highest_score']:.2f} · {stats['lowest_score']:.2f}"
            ),
            inline=False,
        )
        e.add_field(
            name="TECHNOLOGY",
            value=(
                "discord.py 2.x · PostgreSQL · vaderSentiment · langdetect · deep-translate"
            ),
            inline=False,
        )
        e.add_field(
            name="LINKS",
              value=f"[Source Code]({REPO_URL}) · [Invite to Server]({INVITE_URL}) · [Public Dashboard]({DASHBOARD_URL})",
            inline=False,
        )
        e.add_field(
            name="★ SUPPORT SERVER ★",
            value=f"[Join here]({SUPPORT_URL}) · changelogs and updates posted constantly, this is the place to follow.\nAlso join for a +15% yuan boost globally!",
            inline=False,
        )

        e.set_footer(text="Disclaimer: see /disclaimer")
        await interaction.followup.send(embed=e, file=discord.File("images/bureau.png"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
