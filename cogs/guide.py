import re
import random
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config.ranks import RANKS
from config.market_hours import all_exchange_status as _all_exchange_status, EXCHANGE_NAMES as _EXCHANGE_NAMES

log = logging.getLogger(__name__)

REPO_URL      = "https://github.com/Saguny/Social-Score-Surveillant_Discord-Bot"
INVITE_URL    = "https://discord.com/oauth2/authorize?client_id=856163780265902151&permissions=2416438352&integration_type=0&scope=bot"
TOPGG_URL     = "https://top.gg/bot/856163780265902151/invite"
SUPPORT_URL   = "https://discord.gg/invite/k4W6YAPYhC"
DASHBOARD_URL = "https://off-by-one.digital/social-credit/dashboard"
WIKIQUOTE_API = "https://en.wikiquote.org/w/api.php"

BUREAU_IMAGE    = Path("images/security.png")
THEME_RED       = 0xCC0000
THEME_DARK      = 0x333333
TREASURY_CHANCE = 0.15
QUOTE_REFRESH   = 24
VIEW_TIMEOUT    = 1800

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
    discord.SelectOption(label="State Decorations", value="achievements", description="Achievement system overview"),
    discord.SelectOption(label="Waifu Bureau",      value="gacha",        description="Roll, claim, trade, and collect historical waifus"),
    discord.SelectOption(label="Mod Commands",      value="mod",          description="Mod-only commands and server settings"),
    discord.SelectOption(label="Privacy & Legal",   value="privacy",      description="/optout, /optin, and disclaimer"),
]


class GuideView(discord.ui.View):
    def __init__(self, exchange_status: dict):
        super().__init__(timeout=VIEW_TIMEOUT)
        self._exchange_status = exchange_status

    @staticmethod
    def bureau_embed(title: str, description: str = "中华人民共和国社会信用局", *, color: int = THEME_RED) -> discord.Embed:
        return discord.Embed(title=title, description=description, color=color)

    def build(self, topic: str) -> discord.Embed:
        e = getattr(self, f"_page_{topic}")()
        e.set_thumbnail(url="attachment://security.png")
        e.set_footer(text=f"{len(_TOPIC_OPTIONS)} sections, select a topic from the menu below · GLORY TO THE CCP!")
        return e

    @discord.ui.select(placeholder="Select a topic...", options=_TOPIC_OPTIONS)
    async def select_topic(self, interaction: discord.Interaction, select: discord.ui.Select):
        await interaction.response.edit_message(embed=self.build(select.values[0]))

    def _page_overview(self) -> discord.Embed:
        e = self.bureau_embed("OVERVIEW")
        e.add_field(
            name="THE SYSTEM",
            value=(
                "Every citizen begins with **750 Social Credit**. Every message you send strengthens - or weakens - "
                "the Nation's faith in you. Rise through the Party ranks, amass your fortune, earn prestigious State Decorations, "
                "and prove yourself worthy of history's approval."
            ),
            inline=False,
        )
        e.add_field(name="YUAN",             value=f"The currency of the state. Earned through productivity. Spent on influence. [Support server]({SUPPORT_URL}) members earn +15% on every contribution.", inline=False)
        e.add_field(name="WHAT AWAITS YOU",  value="Party ranks · State Decorations · Prestige · Global Standing · Propaganda Events · The Beijing Stock Exchange · **Waifu Bureau**", inline=False)
        e.add_field(name="YOUR FIRST INSPECTION", value="Report to `/checkin` and cast your `/vote` on Top.gg on the same day - the two combine for a bonus payout on top of either reward alone. Review your `/score`. The Nation will determine your worth.", inline=False)
        e.add_field(name="BUREAU RESOURCES", value=f"[Public Dashboard]({DASHBOARD_URL}) · [Support Server]({SUPPORT_URL}) · [Invite the Bureau]({INVITE_URL})", inline=False)
        return e

    def _page_scoring(self) -> discord.Embed:
        e = self.bureau_embed("SCORING RULES")
        e.add_field(name="IDEOLOGICAL ASSESSMENT",     value="Every message is evaluated for loyalty. Maximum impact: **+0.30** or **-0.30** per message. Neutral civic participation earns **+0.03**.", inline=False)
        e.add_field(name="SUSTAINED LOYALTY BONUS",    value="Consecutive positive messages build a multiplier. Sustained loyalty of 15+ messages earns up to **1.5x** impact.", inline=False)
        e.add_field(name="CONDUCT VIOLATIONS",         value="Repeated message (10+ chars): **-0.70** · Excessive use of capitals (80%+, 16+ chars): **-0.40**", inline=False)
        e.add_field(name="COUNTER-REVOLUTIONARY CONTENT", value="Any reference to Tiananmen, Taiwan independence, Xinjiang, Tibet, Falun Gong, or related matters: **-0.30**, regardless of tone.", inline=False)
        e.add_field(name="DAILY CONTRIBUTION CEILING", value="Rating gains are capped at **+8.00 net per day**. Beyond **+6.00**, further contributions yield 25% effect. Penalties are always applied in full.", inline=False)
        e.add_field(name="NEGLECT OF CIVIC DUTY",      value="Citizens inactive for 7 or more days will be nudged back toward 750 each day until they resume their responsibilities.", inline=False)
        return e

    def _page_ranks(self) -> discord.Embed:
        e = self.bureau_embed("RANKS & EXECUTION")
        rank_lines = "\n".join(f"{r['min']:>4} – {r['max']:>4}  {r['name']}" for r in RANKS)
        e.add_field(name="PARTY HIERARCHY",   value=f"```\n{rank_lines}\n```", inline=False)
        e.add_field(
            name="THE NATION'S VERDICT",
            value=(
                "Citizens whose loyalty falls to **610 or below** are declared unfit for continued trust "
                "and placed on tomorrow's Execution List. Their assets are confiscated and redistributed among "
                "more loyal citizens. Redemption remains possible - restore your rating above 611 before the sentence is carried out."
            ),
            inline=False,
        )
        e.add_field(name="LOYALTY COMPENSATION", value="Promotions are rewarded with Yuan scaled to your new tier. Demotions carry a financial penalty based on the rank you leave behind.", inline=False)
        e.add_field(name="OFFICIAL DESIGNATIONS", value="Rank roles are assigned automatically on each rating change. Mods may disable with `ccp roles off`. The Execution List role is not optional.", inline=False)
        e.add_field(name="/prestige",             value="Citizens who reach **1290** may sacrifice their rating back to 750 for a permanent prestige mark visible across every server. Yuan resets to 0. The sacrifice is recorded.", inline=False)
        return e

    def _page_stats(self) -> discord.Embed:
        e = self.bureau_embed("BUREAU RECORDS")
        e.add_field(name="/score [citizen]",                value="Your current Social Credit rating, Party rank, and position among all registered citizens.", inline=False)
        e.add_field(name="/stats [citizen]",                value="Your full dossier - **Overview** (rating, trends, rank streak) · **Social** (commendations, censures) · **Economy** (yuan, lottery, check-in streak).", inline=False)
        e.add_field(name="/daily_report [citizen]",         value="Today's Bureau Briefing - rating gained and lost, message counts, and your yuan balance versus yesterday.", inline=False)
        e.add_field(name="/leaderboard",                    value="The National Registry - 6 pages: Loyalty · Treasury · Conduct · Surveillance · Markets · Patriots.", inline=False)
        e.add_field(name="/globalrank me",                  value="Your Global Standing - cross-server balance, average rating, total earned, and your rank among all citizens worldwide.", inline=False)
        e.add_field(name="/globalrank top",                 value="The global National Registry - Top Balance · Top Earned · Top Rating · Top Citizens. Also live on the web dashboard.", inline=False)
        e.add_field(name="/globalrank visibility <on|off>", value="Declare yourself to the global leaderboard and web dashboard, or remain anonymous. Your choice is noted either way.", inline=False)
        e.add_field(name="/state_report",                   value="The National Report - server-wide rating activity, yuan in circulation, and active citizen count.", inline=False)
        e.add_field(name="/graph <score|yuan> [citizen]",   value="30-day trend graph. Observe your loyalty trajectory or the growth of your fortune.", inline=False)
        e.add_field(name="/checkin",                        value="Daily civic duty. Earns Yuan and rating across every server you share with the Bureau. Streak builds up to ¥2,000/day.", inline=False)
        e.add_field(
            name="SERVER RANKINGS",
            value=(
                "`/serverrank top` · Browse the server leaderboard by metric and size bracket\n"
                "`/serverrank me` · This server's full almanac profile, bracket ranking, and rival server\n"
                "`/serverrank card` · Generate a shareable rank card image for this server\n"
                "`/serverrank visibility [on|off]` · Show your server's real name on the public leaderboard"
            ),
            inline=False,
        )
        return e

    def _page_economy(self) -> discord.Embed:
        e = self.bureau_embed("ECONOMY")
        e.add_field(
            name="PRODUCTIVITY COMPENSATION",
            value=(
                f"Productive citizens receive **¥10** for each contribution to society · [Support server]({SUPPORT_URL}) members receive +15% globally\n"
                "After 25 contributions per day, marginal output is compensated at 25% · Resets at midnight UTC\n"
                "**Prosperity contribution:** citizens holding ¥100,000 or more generously share 10% of each new credit with the Bureau Treasury"
            ),
            inline=False,
        )
        e.add_field(name="/yuan",                           value="Review your state account balance, lifetime earnings, and total expenditure.", inline=False)
        e.add_field(name="/transfer <citizen> <amount>",    value="Transfer Yuan to another citizen. The Bureau observes all transactions. Confirmation required.", inline=False)
        e.add_field(name="/requestyuan <citizen> <amount>", value="Submit a formal Yuan request to another citizen. They may Accept or Decline. Request expires in 5 minutes.", inline=False)
        e.add_field(name="/battle <opponent> <amount>",     value="Economic arbitration by coin flip. Minimum ¥1,000 at risk. Winner claims all. Opponent must consent within 5 minutes.", inline=False)
        e.add_field(name="/confess <text>",                 value="Public confession to the Bureau. Cost scales with your rating deficit (¥200–¥750). Grants +0.50 rating. 1-hour cooldown.", inline=False)
        e.add_field(
            name="/vote",
            value=(
                "Cast your ballot on Top.gg. Earns the **Loyal Patriot** badge, +2.00 rating, and ¥1,500 or more on every shared server. "
                "Reward scales with streak, weekend multiplier, and a fortunate draw. Badge lasts 12 hours - vote again to renew your standing."
            ),
            inline=False,
        )
        return e

    def _page_shop(self) -> discord.Embed:
        e = self.bureau_embed("THE BUREAU SHOP")
        e.add_field(name="/shop", value="Browse all available instruments across 5 categories: **Core** · **Economy** · **Misc** · **Lottery** · **Cosmetic**.", inline=False)
        e.add_field(
            name="INSTRUMENTS OF STATE  ·  /buy <item_id> [target]",
            value=(
                "`report` ¥2,500 · File a silent report. Docks target -2.00 rating\n"
                "`denounce` ¥12,000 · Public censure. Docks target -20.00 rating · 48h cooldown per target\n"
                "`rehabilitate` ¥3,000+ · Restore +3.00 rating. Cost doubles with each use · Gift-eligible\n"
                "`appeal` ¥2,500 · Halve the next incoming penalty of -1.00 or worse (12h window) · Gift-eligible\n"
                "`exception` ¥12,000 · Nullify the next negative action entirely (24h window) · Gift-eligible\n"
                "`reeducation` ¥12,000 · Suspend a target's rating for 2h\n"
                "`media_coverage` ¥15,000 · Arrange immediate State Media coverage. Grants +4.00 rating · Gift-eligible"
            ),
            inline=False,
        )
        e.add_field(
            name="THE PEOPLE'S LOTTERY",
            value=(
                "All tiers: 70% loss · 20% win · 10% jackpot. Add `target` to purchase on another citizen's behalf.\n"
                "`lottery` ¥500 · `lottery_standard` ¥2,500 · `lottery_premium` ¥10,000\n"
                "`lottery_elite` ¥50,000 · `lottery_chairman` ¥250,000"
            ),
            inline=False,
        )
        e.add_field(name="GIFTING", value="Add a `target` to any gift-eligible instrument to deliver it publicly with a recorded statement.", inline=False)
        return e

    def _page_social(self) -> discord.Embed:
        e = self.bureau_embed("SOCIAL RATING")
        e.add_field(name="/endorse <citizen> [reason]", value="File an official commendation. Grants the target **+1.5 rating**. One filing per citizen per 24 hours. Statement is entered into the public record.", inline=False)
        e.add_field(name="/rebuke <citizen> [reason]",  value="File an official censure. Applies **-1.5 rating** to the target. One filing per citizen per 24 hours. Statement is entered into the public record.", inline=False)
        e.add_field(
            name="COLLECTIVE FUNDRAISING",
            value=(
                "`/fundraise create <goal> <desc>` · Open a fundraiser with a stated Yuan target\n"
                "`/fundraise donate <id> <amount>` · Contribute Yuan, held in escrow until resolution\n"
                "`/fundraise complete <id>` · Declare completion and open the public vote phase\n"
                "`/fundraise vote <id> <confirm|deny>` · Vote on whether the organiser fulfilled their obligation\n"
                "`/fundraise list` · Active campaigns · `/fundraise info <id>` · Full details"
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

        e = self.bureau_embed("MARKETS", "北京证券交易所")
        e.add_field(name="EXCHANGE STATUS", value="\n".join(hours_lines), inline=False)
        e.add_field(
            name="APPROVED SECURITIES",
            value=(
                "5 China ADRs (NYSE) · 3 LSE blue chips · 3 TSE blue chips · 1 ETF (CNXF) · 5 Penny stocks\n"
                "All prices denominated in Yuan. Trading is suspended when the relevant exchange is closed.\n"
                "Citizens holding stocks at 2%+ unrealized gain contribute to their social rating - up to **+0.30/day**."
            ),
            inline=False,
        )
        e.add_field(
            name="TRADING COMMANDS",
            value=(
                "`/market` · Live prices across all securities\n"
                "`/stocks chart <ticker> [period]` · Price chart (1D 5D 1M 3M 6M 1Y)\n"
                "`/stocks buy <ticker> <shares>` · Acquire shares\n"
                "`/stocks sell <ticker> <shares>` · Liquidate shares\n"
                "`/stocks portfolio` · Open positions with live P&L"
            ),
            inline=False,
        )
        e.add_field(
            name="TURBO CERTIFICATES",
            value=(
                "12 instruments generated daily. Leveraged long or short with a knockout barrier.\n"
                "Leverage: 2x 3x 5x 7x 10x - position is closed automatically if the barrier is breached.\n"
                "`/turbos list` · Today's instruments · `/turbos open <id> <yuan>` · `/turbos close <pos_id>`"
            ),
            inline=False,
        )
        e.add_field(name="CIRCUIT BREAKERS", value="7% intraday move triggers a 15-minute trading halt. 20% daily move locks the ticker for the remainder of the session.", inline=False)
        return e

    def _page_events(self) -> discord.Embed:
        e = self.bureau_embed("EVENTS & POSTERS")
        e.add_field(name="ccp poster",         value="Display a propaganda poster selected from the Bureau's archive. Available to all citizens at any time.", inline=False)
        e.add_field(name="DAILY BROADCASTS",   value="Enabled by a moderator. A new poster is issued daily at 12:00 UTC. React ❤️ for **+3 rating and ¥250**. React 😡 for **-1 rating**. The Nation is watching.", inline=False)
        e.add_field(
            name="PROPAGANDA SUBMISSION EVENTS",
            value=(
                "1. A moderator opens a submission window with `/propaganda start`\n"
                "2. Citizens submit their slogans via `/propaganda submit <text>` (max 280 chars)\n"
                "3. When the deadline passes, all submissions are revealed for public reaction voting\n"
                "4. The most-approved submission is enshrined as an official guild decree, retrievable via `/decree`"
            ),
            inline=False,
        )
        e.add_field(name="COUNTER-REVOLUTIONARY SUBMISSIONS", value="Any submission found to contain banned content incurs **-5.00 rating** and a permanent ban from that event.", inline=False)
        return e

    def _page_achievements(self) -> discord.Embed:
        e = self.bureau_embed("STATE DECORATIONS")
        e.add_field(
            name="/achievements [citizen]",
            value="Review this citizen's official decoration record, sorted by category. Classified citations withhold all details until the criteria have been met.",
            inline=False,
        )
        e.add_field(name="CATEGORIES",        value="Score · Economy · Social · Markets · Propaganda · Joke", inline=False)
        e.add_field(name="WHAT YOU RECEIVE",  value="Most decorations carry a Yuan grant, a rating adjustment, or a cosmetic designation displayed in your profile header.", inline=False)
        e.add_field(name="RARITY",            value="Each decoration displays the percentage of citizens who have received it. Some are extremely rare. Some are secret.", inline=False)
        e.add_field(name="MOD CONFIGURATION", value="`ccp achievementnotification [on|off]` · `ccp achievementchannel [#channel]`", inline=False)
        return e

    def _page_gacha(self) -> discord.Embed:
        e = self.bureau_embed("WAIFU BUREAU", "中华人民共和国恋爱局")
        e.add_field(
            name="THE SYSTEM",
            value=(
                "Roll for historical and political waifus drawn from real Wikipedia figures. "
                "Each waifu belongs to a **faction** and a **rarity tier**. "
                "The first citizen to react to a roll claims them — and gets married. "
                "Your collection is per-server."
            ),
            inline=False,
        )
        e.add_field(
            name="ROLLING",
            value=(
                "`ccp roll` · `ccp r` · `/roll` — Roll a random waifu\n"
                "`ccp rollwaifu` · `ccp rw` · `/rollwaifu` — Female figures only\n"
                "`ccp rollhusbando` · `ccp rh` · `/rollhusbando` — Male figures only\n"
                "React with any emoji to claim · **10 rolls per hour** base\n"
                "Vote streak adds up to +4 rolls · Accelerated Processing upgrade adds up to +20\n"
                "Voting on Top.gg resets your hourly rolls instantly"
            ),
            inline=False,
        )
        e.add_field(
            name="RARITY TIERS",
            value=(
                "🟡 **Legendary** — global icons (≥2M monthly views)\n"
                "🟣 **Epic** — major historical figures (≥500k)\n"
                "🔵 **Rare** — notable figures (≥80k)\n"
                "🟢 **Uncommon** — regional figures (≥15k)\n"
                "⚪ **Common** — everyone else"
            ),
            inline=False,
        )
        e.add_field(
            name="ALREADY CLAIMED",
            value=(
                "If a rolled waifu is already claimed in this server, the embed turns gold. "
                "The first reactor earns Yuan instead — scaled by rarity "
                "(¥100 common -> ¥5,000 legendary). Does not count against your roll limit."
            ),
            inline=False,
        )
        e.add_field(
            name="COLLECTION & VIEWING",
            value=(
                "`ccp collection` · `ccp harem` · `/collection` — View your harem\n"
                "`ccp hi` · `ccp haremimage` · `/haremimage` — Browse your harem images one by one (◀▶ to navigate, loops)\n"
                "`ccp image <name>` · `ccp im <name>` · `/image <name>` — View a waifu's image (◀▶ to browse multiple)\n"
                "`ccp browse` · `/browse` — Full catalogue with faction/rarity filters\n"
                "`ccp top` · `/top` — Most claimed waifus globally"
            ),
            inline=False,
        )
        e.add_field(
            name="TRADING & GIFTING",
            value=(
                "`/trade <@user> <offer> <request>` — Propose a swap · target must accept\n"
                "`ccp gift <name> <@user>` · `/gift <name> <@user>` — Give a waifu away\n"
                "`ccp divorce <name>` · `/divorce <name>` — Remove a waifu from your harem"
            ),
            inline=False,
        )
        e.add_field(
            name="WISHLIST",
            value=(
                "`ccp wish <name>` — Add to wishlist (10 slots base, up to 30 with upgrades) · you'll be DM'd when they're claimed\n"
                "`ccp wl` · `ccp wishlist` · `/wishlist view` — View your wishlist\n"
                "`/wishlist remove <name>` — Remove from wishlist\n"
                "Wishlisted characters have a 6% base chance to be forced on each roll (upgradeable to 15%)"
            ),
            inline=False,
        )
        e.add_field(
            name="BUREAU UPGRADES",
            value=(
                "Permanent account upgrades purchased via `/buy`. Four tiers each.\n"
                "**Expanded Dossier** (`/buy gacha_slots`) — wishlist capacity 10 → 15/20/25/30\n"
                "**Accelerated Processing** (`/buy gacha_rolls`) — bonus rolls/hr +2/+5/+10/+20\n"
                "**Priority Routing** (`/buy gacha_spawn`) — wishlist spawn rate 6% → 7.5/9.4/11.7/15%\n"
                "View current tiers: `ccp upgrades`"
            ),
            inline=False,
        )
        return e

    def _page_mod(self) -> discord.Embed:
        e = self.bureau_embed("MOD COMMANDS", color=THEME_DARK)
        e.add_field(name="NOTE", value="Prefix commands typed directly in chat. Requires **Manage Server** permission.", inline=False)
        e.add_field(
            name="CITIZEN MANAGEMENT",
            value=(
                "`ccp initialize` · Register all current members\n"
                "`ccp adjust <@citizen> <delta> <reason>` · Manual rating adjustment\n"
                "`ccp reset <@citizen>` · Reset rating to 750"
            ),
            inline=False,
        )
        e.add_field(
            name="SERVER SETTINGS",
            value=(
                "`ccp threshold <n>` · Fundraiser vote threshold (default 3)\n"
                "`ccp rankchannel [#channel]` · Dedicated rank-up announcement channel\n"
                "`ccp executions [#channel]` · Dedicated execution notice channel\n"
                "`ccp roles [on|off]` · Toggle rank role assignment"
            ),
            inline=False,
        )
        e.add_field(
            name="DECORATIONS & POSTERS",
            value=(
                "`ccp achievementnotification [on|off]` · Toggle decoration announcements\n"
                "`ccp achievementchannel [#channel]` · Dedicated decoration channel\n"
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
        e = self.bureau_embed("PRIVACY & LEGAL")
        e.add_field(
            name="/optout",
            value=(
                "Permanently opt out of the Social Credit System. Stops message scoring and blocks all commands. "
                "Permanently deletes all data tied to your Discord ID across every server: rating, yuan, history, decorations, "
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
            headers = {"User-Agent": "SocialCreditBot/1.0 (https://github.com/saguny/social-credit-bot; bot)"}
            async with self._session.get(WIKIQUOTE_API, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                data = await resp.json(content_type=None)
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
            log.exception("Failed to fetch Wikiquote quotes")

    @tasks.loop(hours=QUOTE_REFRESH)
    async def _refresh_quotes(self):
        await self._fetch_quotes()

    @_refresh_quotes.before_loop
    async def _before_refresh(self):
        await self.bot.wait_until_ready()

    def _make_guide_view(self) -> tuple[GuideView, discord.Embed]:
        view = GuideView(_all_exchange_status())
        return view, view.build("overview")

    async def _send_guide(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        view, embed = self._make_guide_view()
        await interaction.followup.send(embed=embed, view=view, file=discord.File(BUREAU_IMAGE, filename="security.png"), ephemeral=True)

    @app_commands.command(name="guide", description="Full guide to the Social Credit System")
    async def guide(self, interaction: discord.Interaction):
        await self._send_guide(interaction)

    @app_commands.command(name="help", description="Full guide to the Social Credit System")
    async def help(self, interaction: discord.Interaction):
        await self._send_guide(interaction)

    @commands.command(name="help")
    async def help_prefix(self, ctx: commands.Context):
        view, embed = self._make_guide_view()
        await ctx.reply(embed=embed, view=view, file=discord.File(BUREAU_IMAGE, filename="security.png"))

    @app_commands.command(name="ping", description="Check the Bureau's response latency")
    async def ping(self, interaction: discord.Interaction):
        latency_ms = round(self.bot.latency * 1000)
        e = discord.Embed(
            color=0xCC0000,
            title="SIGNAL CHECK",
            description=f"中华人民共和国社会信用局\n\nThe Bureau responds in **{latency_ms} ms**. Your transmission has been logged.",
        )
        e.set_thumbnail(url="attachment://security.png")
        await interaction.response.send_message(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"), ephemeral=True)

    @app_commands.command(name="decree", description="Receive an official proclamation from the Bureau")
    async def decree(self, interaction: discord.Interaction):
        if random.random() < TREASURY_CHANCE:
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
            title="OFFICIAL DECREE",
            description=f"中华人民共和国社会信用局\n\n{description}",
        )
        await interaction.response.send_message(embed=e)

    @app_commands.command(name="credits", description="Open-source libraries powering the Bureau")
    async def credits(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="ACKNOWLEDGEMENTS",
            description="中华人民共和国社会信用局\n\nThe surveillance apparatus is built on the following open-source technologies. The Party is grateful.",
        )
        e.set_thumbnail(url="attachment://security.png")
        for name, desc in CREDITS_LINES:
            e.add_field(name=name, value=desc, inline=False)
        e.add_field(name="SOURCE CODE", value=f"[GitHub]({REPO_URL})", inline=False)
        await interaction.response.send_message(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"), ephemeral=True)

    @app_commands.command(name="disclaimer", description="Legal and ethical disclaimer for this bot")
    async def disclaimer(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="DISCLAIMER",
            description=(
                "中华人民共和国社会信用局\n\n"
                "This bot is a **satirical meme project** and is not affiliated with, endorsed by, "
                "or representative of the Chinese Communist Party or the Chinese government.\n\n"
                "The creator does not support, condone, or endorse the human rights abuses, "
                "authoritarian policies, or surveillance practices of the CCP, including but not "
                "limited to the treatment of Uyghurs, Tibetans, Hong Kongers, and political dissidents, "
                "the Tiananmen Square massacre, or real-world social credit systems.\n\n"
                "This is a joke. The irony is the point."
            ),
        )
        e.set_thumbnail(url="attachment://security.png")
        await interaction.response.send_message(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"))

    @app_commands.command(name="invite", description="Invite the Bureau to expand to another server")
    async def invite(self, interaction: discord.Interaction):
        e = discord.Embed(
            color=0xCC0000,
            title="EXPAND THE BUREAU",
            description="中华人民共和国社会信用局\n\nBring social credit surveillance to your own server. Compliance is mandatory. Resistance is futile.",
        )
        e.set_thumbnail(url="attachment://security.png")
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Add to Server", style=discord.ButtonStyle.link, url=TOPGG_URL))
        view.add_item(discord.ui.Button(label="Support Server", style=discord.ButtonStyle.link, url=SUPPORT_URL))
        await interaction.response.send_message(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"), view=view)

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

        parts = [p for p in [
            f"{days}d"    if days    else None,
            f"{hours}h"   if hours   else None,
            f"{minutes}m" if minutes else None,
            f"{seconds}s",
        ] if p]

        e = discord.Embed(
            color=0xCC0000,
            title="BUREAU STATUS",
            description=f"中华人民共和国社会信用局\n\nThe Bureau has been vigilant for **{' '.join(parts)}**.",
        )
        e.add_field(name="ONLINE SINCE", value=f"<t:{int(start_time.timestamp())}:F>", inline=False)
        e.set_thumbnail(url="attachment://security.png")
        await interaction.followup.send(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"), ephemeral=True)

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
            title="BOT INFORMATION",
            description=(
                "中华人民共和国社会信用局\n\n"
                "An authoritative CCP-themed social credit system for Discord. "
                "Every citizen is monitored. Every message is evaluated. Glory awaits the compliant."
            ),
        )
        e.set_thumbnail(url="attachment://security.png")
        e.add_field(name="VERSION",  value="1.0.3",                                    inline=True)
        e.add_field(name="CREATOR",  value="OFF-BY-ONE (saguny & digitalwarpstar)",    inline=True)
        e.add_field(name="LATENCY",  value=f"{discord_ms} ms discord · {db_ms} ms database", inline=True)
        e.add_field(
            name="GLOBAL STATISTICS",
            value=(
                f"**Servers · Citizens** · {guild_count} servers · {member_count:,} citizens\n"
                f"**Yuan in Circulation** · ¥{stats['total_yuan']:,}\n"
                f"**Bureau Treasury** · ¥{stats['treasury_total']:,}\n"
                f"**Messages Rated** · {stats['total_messages']:,}\n"
                f"**Highest · Lowest Rating** · {stats['highest_score']:.2f} · {stats['lowest_score']:.2f}"
            ),
            inline=False,
        )
        e.add_field(name="TECHNOLOGY",    value="discord.py 2.x · PostgreSQL · vaderSentiment · langdetect · deep-translate", inline=False)
        e.add_field(name="LINKS",         value=f"[Source Code]({REPO_URL}) · [Invite to Server]({INVITE_URL}) · [Public Dashboard]({DASHBOARD_URL})", inline=False)
        e.add_field(name="SUPPORT SERVER", value=f"[Join here]({SUPPORT_URL}) · Changelogs and updates posted constantly. Also join for a +15% yuan boost globally.", inline=False)
        e.set_footer(text="See /disclaimer for full legal notice.")
        await interaction.followup.send(embed=e, file=discord.File(BUREAU_IMAGE, filename="security.png"))


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
