import os
import time
import asyncpg

from database._core        import CoreMixin
from database._effects     import EffectsMixin
from database._ranks       import RanksMixin
from database._social      import SocialMixin
from database._economy     import EconomyMixin
from database._fundraisers import FundraisersMixin
from database._propaganda  import PropagandaMixin
from database._posters     import PostersMixin
from database._stocks      import StocksMixin
from database._voting      import VotingMixin
from database._stats       import StatsMixin
from database._achievements import AchievementsMixin
from database._counters     import CountersMixin
from database._privacy      import PrivacyMixin
from database._announcement import AnnouncementMixin
from database._guilds       import GuildRankMixin
from database._analytics    import AnalyticsMixin
from database._gacha        import GachaMixin
from database._requests     import GachaRequestsMixin


TABLES = [
    """
    CREATE TABLE IF NOT EXISTS guild_config (
        guild_id          BIGINT  PRIMARY KEY,
        report_counter    INTEGER DEFAULT 0,
        confirm_threshold INTEGER DEFAULT 3,
        guild_name        TEXT    DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS endorsements (
        guild_id   BIGINT,
        giver_id   BIGINT,
        target_id  BIGINT,
        type       TEXT,
        timestamp  BIGINT,
        PRIMARY KEY (guild_id, giver_id, target_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundraisers (
        id          SERIAL  PRIMARY KEY,
        guild_id    BIGINT,
        creator_id  BIGINT,
        description TEXT,
        goal        INTEGER,
        raised      INTEGER DEFAULT 0,
        status      TEXT    DEFAULT 'open',
        channel_id  BIGINT,
        message_id  BIGINT,
        created_at  BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundraiser_donations (
        id            SERIAL PRIMARY KEY,
        fundraiser_id INTEGER,
        guild_id      BIGINT,
        donor_id      BIGINT,
        amount        INTEGER,
        timestamp     BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS fundraiser_votes (
        fundraiser_id INTEGER,
        voter_id      BIGINT,
        vote          TEXT,
        PRIMARY KEY (fundraiser_id, voter_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS users (
        guild_id             BIGINT,
        user_id              BIGINT,
        score                DOUBLE PRECISION DEFAULT 750.0,
        yuan                 INTEGER DEFAULT 0,
        message_count        INTEGER DEFAULT 0,
        has_chatted          INTEGER DEFAULT 0,
        highest_score        DOUBLE PRECISION DEFAULT 750.0,
        lowest_score         DOUBLE PRECISION DEFAULT 750.0,
        times_reported       INTEGER DEFAULT 0,
        times_filed_reports  INTEGER DEFAULT 0,
        total_yuan_earned    INTEGER DEFAULT 0,
        total_yuan_spent     INTEGER DEFAULT 0,
        times_endorsed       INTEGER DEFAULT 0,
        times_rebuked        INTEGER DEFAULT 0,
        endorsements_given   INTEGER DEFAULT 0,
        rebukes_given        INTEGER DEFAULT 0,
        items_bought         INTEGER DEFAULT 0,
        PRIMARY KEY (guild_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS score_history (
        id         SERIAL PRIMARY KEY,
        guild_id   BIGINT,
        user_id    BIGINT,
        delta      DOUBLE PRECISION,
        reason     TEXT,
        timestamp  BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS active_effects (
        id          SERIAL PRIMARY KEY,
        guild_id    BIGINT,
        user_id     BIGINT,
        effect_type TEXT,
        metadata    TEXT DEFAULT '{}',
        expires_at  BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS transactions (
        id             SERIAL PRIMARY KEY,
        guild_id       BIGINT,
        user_id        BIGINT,
        item_id        TEXT,
        cost           INTEGER,
        target_user_id BIGINT,
        timestamp      BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS poster_config (
        guild_id   BIGINT PRIMARY KEY,
        channel_id BIGINT,
        last_slug  TEXT DEFAULT ''
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS poster_messages (
        guild_id   BIGINT,
        message_id BIGINT,
        channel_id BIGINT,
        PRIMARY KEY (guild_id, message_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS poster_reactions (
        message_id BIGINT,
        user_id    BIGINT,
        PRIMARY KEY (message_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS propaganda_events (
        id                SERIAL  PRIMARY KEY,
        guild_id          BIGINT,
        mod_id            BIGINT,
        submit_channel_id BIGINT,
        reveal_channel_id BIGINT,
        closes_at         BIGINT,
        concludes_at      BIGINT,
        status            TEXT    DEFAULT 'open'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS propaganda_submissions (
        id                SERIAL  PRIMARY KEY,
        event_id          INTEGER,
        guild_id          BIGINT,
        user_id           BIGINT,
        content           TEXT,
        timestamp         BIGINT,
        reveal_message_id BIGINT  DEFAULT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS propaganda_event_bans (
        event_id        INTEGER,
        guild_id        BIGINT,
        user_id         BIGINT,
        matched_content TEXT,
        PRIMARY KEY (event_id, user_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS guild_decrees (
        id         SERIAL  PRIMARY KEY,
        guild_id   BIGINT,
        user_id    BIGINT,
        content    TEXT,
        won_at     BIGINT,
        vote_count INTEGER DEFAULT 0
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eternal_chairmen (
        user_id      BIGINT PRIMARY KEY,
        purchased_at BIGINT
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS bureau_treasury (
        id    INTEGER PRIMARY KEY DEFAULT 1,
        total BIGINT NOT NULL DEFAULT 0,
        CONSTRAINT single_row CHECK (id = 1)
    )
    """,
]


class Database(
    CoreMixin,
    EffectsMixin,
    RanksMixin,
    SocialMixin,
    EconomyMixin,
    FundraisersMixin,
    PropagandaMixin,
    PostersMixin,
    StocksMixin,
    VotingMixin,
    StatsMixin,
    AchievementsMixin,
    CountersMixin,
    PrivacyMixin,
    AnnouncementMixin,
    GuildRankMixin,
    AnalyticsMixin,
    GachaMixin,
    GachaRequestsMixin,
):
    def __init__(self):
        self._dsn = os.getenv("DATABASE_URL", "")
        self._pool: asyncpg.Pool | None = None
        self._last_clean_effects: float = 0.0
        self._pool_min = int(os.getenv("DB_POOL_MIN", "2"))
        self._pool_max = int(os.getenv("DB_POOL_MAX", "10"))

    async def init(self):
        ssl = "require" if "sslmode" not in self._dsn and not self._dsn.startswith("postgresql://localhost") and not self._dsn.startswith("postgresql://127.") else None
        self._pool = await asyncpg.create_pool(self._dsn, min_size=self._pool_min, max_size=self._pool_max, ssl=ssl)
        await self._create_tables()
        await self._migrate()

    async def _create_tables(self):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for ddl in TABLES:
                    await conn.execute(ddl)

    async def _migrate(self):
        async with self._pool.acquire() as conn:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_checkin BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS checkin_streak INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS longest_checkin_streak INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS propaganda_wins INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS rank_entered_at BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS prev_day_yuan BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lottery_played INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lottery_won    INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lottery_lost   INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS lottery_net    BIGINT  NOT NULL DEFAULT 0")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_score_history_timestamp ON score_history (timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_score_history_reason ON score_history (reason)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_active ON users (last_active)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_checkin ON users (last_checkin)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_has_chatted_guild ON users (has_chatted, guild_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_score_history_user_ts ON score_history (guild_id, user_id, timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_turbo_positions_status ON turbo_positions (status) WHERE status = 'open'")
            await conn.execute("ALTER TABLE portfolios ADD COLUMN IF NOT EXISTS opened_at BIGINT")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_history (
                    guild_id BIGINT NOT NULL,
                    user_id  BIGINT NOT NULL,
                    ts       BIGINT NOT NULL,
                    value    BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, ts)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_portfolio_history_user_ts ON portfolio_history (guild_id, user_id, ts)")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS execution_channel_id BIGINT")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS rank_announcement_channel_id BIGINT")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS assign_rank_roles BOOLEAN NOT NULL DEFAULT TRUE")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS daily_yuan_snapshots (
                    guild_id BIGINT,
                    user_id  BIGINT,
                    day      BIGINT,
                    yuan     BIGINT,
                    PRIMARY KEY (guild_id, user_id, day)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS rank_history (
                    guild_id   BIGINT,
                    user_id    BIGINT,
                    rank_name  TEXT,
                    total_days BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, rank_name)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stocks (
                    ticker        TEXT PRIMARY KEY,
                    price         DOUBLE PRECISION NOT NULL DEFAULT 0,
                    open_price    DOUBLE PRECISION NOT NULL DEFAULT 0,
                    updated_at    BIGINT NOT NULL DEFAULT 0,
                    halted_until  BIGINT NOT NULL DEFAULT 0,
                    daily_locked  BOOLEAN NOT NULL DEFAULT FALSE
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS stock_price_history (
                    id     SERIAL PRIMARY KEY,
                    ticker TEXT NOT NULL,
                    ts     BIGINT NOT NULL,
                    open   DOUBLE PRECISION NOT NULL,
                    high   DOUBLE PRECISION NOT NULL,
                    low    DOUBLE PRECISION NOT NULL,
                    close  DOUBLE PRECISION NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_stock_price_history ON stock_price_history (ticker, ts)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolios (
                    guild_id  BIGINT NOT NULL,
                    user_id   BIGINT NOT NULL,
                    ticker    TEXT NOT NULL,
                    shares    DOUBLE PRECISION NOT NULL DEFAULT 0,
                    avg_cost  DOUBLE PRECISION NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, user_id, ticker)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS turbos (
                    id          SERIAL PRIMARY KEY,
                    ticker      TEXT NOT NULL,
                    direction   TEXT NOT NULL,
                    leverage    INTEGER NOT NULL,
                    entry_price DOUBLE PRECISION NOT NULL,
                    knockout    DOUBLE PRECISION NOT NULL,
                    day         BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS turbo_positions (
                    id         SERIAL PRIMARY KEY,
                    guild_id   BIGINT NOT NULL,
                    user_id    BIGINT NOT NULL,
                    turbo_id   INTEGER NOT NULL,
                    cost       BIGINT NOT NULL,
                    opened_at  BIGINT NOT NULL,
                    closed_at  BIGINT,
                    pnl        BIGINT,
                    status     TEXT NOT NULL DEFAULT 'open'
                )
            """)
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stock_trades  INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS stock_profit  BIGINT  NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS turbo_opened  INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS turbo_knocked INTEGER NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS turbo_profit  BIGINT  NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS traded_exchanges INTEGER NOT NULL DEFAULT 0")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user   ON transactions (guild_id, user_id, item_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_target ON transactions (guild_id, target_user_id, item_id, timestamp DESC)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vote_reminders (
                    user_id   BIGINT PRIMARY KEY,
                    remind_at BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS topgg_votes (
                    user_id  BIGINT NOT NULL,
                    voted_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_topgg_votes_voted_at ON topgg_votes (voted_at)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_joins (
                    guild_id  BIGINT NOT NULL,
                    joined_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_joins_joined_at ON guild_joins (joined_at)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_leaves (
                    guild_id       BIGINT NOT NULL,
                    left_at        BIGINT NOT NULL,
                    member_count   INTEGER,
                    tenure_seconds BIGINT,
                    citizens       INTEGER NOT NULL,
                    score_events   INTEGER NOT NULL,
                    category       TEXT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_leaves_left_at ON guild_leaves (left_at)")
            await conn.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'achievements')
                       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'achievements_legacy_per_guild')
                    THEN
                        ALTER TABLE achievements RENAME TO achievements_legacy_per_guild;
                    END IF;
                END $$;
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS achievements (
                    user_id         BIGINT NOT NULL,
                    achievement_id  TEXT   NOT NULL,
                    unlocked_at     BIGINT NOT NULL,
                    origin_guild_id BIGINT,
                    PRIMARY KEY (user_id, achievement_id)
                )
            """)
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS achievements_channel_id BIGINT")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS achievements_loud_enabled BOOLEAN NOT NULL DEFAULT TRUE")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS execution_count INTEGER NOT NULL DEFAULT 0")
            await conn.execute("""
                DO $$
                BEGIN
                    IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cosmetic_badges')
                       AND NOT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = 'cosmetic_badges_legacy_per_guild')
                    THEN
                        ALTER TABLE cosmetic_badges RENAME TO cosmetic_badges_legacy_per_guild;
                    END IF;
                END $$;
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS cosmetic_badges (
                    user_id      BIGINT NOT NULL,
                    badge        TEXT   NOT NULL,
                    purchased_at BIGINT NOT NULL,
                    expires_at   BIGINT,
                    PRIMARY KEY (user_id, badge)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS badge_preferences (
                    user_id  BIGINT PRIMARY KEY,
                    badge_id TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS user_counters (
                    user_id     BIGINT NOT NULL,
                    counter_key TEXT   NOT NULL,
                    value       BIGINT NOT NULL DEFAULT 0,
                    PRIMARY KEY (user_id, counter_key)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS optouts (
                    user_id      BIGINT PRIMARY KEY,
                    opted_out_at BIGINT NOT NULL
                )
            """)
            await conn.execute(
                "INSERT INTO bureau_treasury (id, total) VALUES (1, 0) ON CONFLICT DO NOTHING"
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS global_yuan_earned_snapshots (
                    user_id           BIGINT NOT NULL,
                    day               BIGINT NOT NULL,
                    total_yuan_earned BIGINT NOT NULL,
                    PRIMARY KEY (user_id, day)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_global_yuan_earned_snapshots_user ON global_yuan_earned_snapshots (user_id, day)")
            await conn.execute(
                """
                INSERT INTO global_yuan_earned_snapshots (user_id, day, total_yuan_earned)
                SELECT user_id, $1, SUM(total_yuan_earned) FROM users GROUP BY user_id
                ON CONFLICT (user_id, day) DO NOTHING
                """,
                int(time.time()) // 86400 * 86400,
            )
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS leaderboard_profiles (
                    user_id      BIGINT PRIMARY KEY,
                    display_name TEXT NOT NULL,
                    updated_at   BIGINT NOT NULL
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS dashboard_announcement (
                    id         INTEGER PRIMARY KEY DEFAULT 1,
                    enabled    BOOLEAN NOT NULL DEFAULT FALSE,
                    message    TEXT,
                    severity   TEXT NOT NULL DEFAULT 'info',
                    updated_at BIGINT NOT NULL DEFAULT 0,
                    CONSTRAINT single_row CHECK (id = 1)
                )
            """)
            await conn.execute(
                "INSERT INTO dashboard_announcement (id, enabled, message, severity, updated_at) "
                "VALUES (1, FALSE, '', 'info', 0) ON CONFLICT DO NOTHING"
            )
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS leaderboard_visible BOOLEAN NOT NULL DEFAULT FALSE")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS guild_daily_snapshots (
                    guild_id       BIGINT NOT NULL,
                    day            BIGINT NOT NULL,
                    total_yuan     BIGINT NOT NULL DEFAULT 0,
                    avg_score      DOUBLE PRECISION NOT NULL DEFAULT 0,
                    total_messages BIGINT NOT NULL DEFAULT 0,
                    citizens       INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY (guild_id, day)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_guild_daily_snapshots_day ON guild_daily_snapshots (day)")
            await conn.execute("ALTER TABLE guild_daily_snapshots ADD COLUMN IF NOT EXISTS literacy_rate DOUBLE PRECISION NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE guild_daily_snapshots ADD COLUMN IF NOT EXISTS incarceration_rate DOUBLE PRECISION NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE guild_daily_snapshots ADD COLUMN IF NOT EXISTS politburo_score DOUBLE PRECISION NOT NULL DEFAULT 0")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS guild_bracket TEXT DEFAULT NULL")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS command_analytics (
                    id                SERIAL  PRIMARY KEY,
                    timestamp         BIGINT  NOT NULL,
                    guild_id          BIGINT  NOT NULL,
                    user_id           BIGINT  NOT NULL,
                    command_name      TEXT    NOT NULL,
                    subcommand        TEXT,
                    execution_time_ms INTEGER NOT NULL DEFAULT 0,
                    success           BOOLEAN NOT NULL DEFAULT TRUE,
                    error_code        TEXT
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_analytics_ts      ON command_analytics (timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_analytics_cmd_ts  ON command_analytics (command_name, timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_cmd_analytics_guild   ON command_analytics (guild_id, timestamp)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_claims (
                    guild_id     BIGINT NOT NULL,
                    user_id      BIGINT NOT NULL,
                    character_id TEXT   NOT NULL,
                    claimed_at   BIGINT NOT NULL,
                    PRIMARY KEY (guild_id, user_id, character_id)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_gacha_claims_user ON gacha_claims (guild_id, user_id, claimed_at DESC)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_wishlists (
                    guild_id     BIGINT NOT NULL,
                    user_id      BIGINT NOT NULL,
                    character_id TEXT   NOT NULL,
                    PRIMARY KEY (guild_id, user_id, character_id)
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_gacha_wish_char ON gacha_wishlists (guild_id, character_id)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_character_stats (
                    character_id TEXT    PRIMARY KEY,
                    claim_count  BIGINT  NOT NULL DEFAULT 0
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_preferences (
                    guild_id     BIGINT NOT NULL,
                    user_id      BIGINT NOT NULL,
                    key          TEXT   NOT NULL,
                    value        TEXT   NOT NULL,
                    PRIMARY KEY (guild_id, user_id, key)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_characters (
                    character_id   TEXT PRIMARY KEY,
                    name           TEXT NOT NULL,
                    title          TEXT NOT NULL DEFAULT '',
                    faction        TEXT NOT NULL DEFAULT 'wildcards',
                    rarity         TEXT NOT NULL DEFAULT 'common',
                    quote          TEXT NOT NULL DEFAULT '',
                    wiki           TEXT NOT NULL DEFAULT '',
                    stat_authority INT  NOT NULL DEFAULT 50,
                    stat_military  INT  NOT NULL DEFAULT 50,
                    stat_charisma  INT  NOT NULL DEFAULT 50,
                    image_urls     TEXT[] NOT NULL DEFAULT '{}',
                    enabled        BOOLEAN NOT NULL DEFAULT TRUE,
                    gender         TEXT DEFAULT NULL
                )
            """)
            await conn.execute("ALTER TABLE gacha_characters ADD COLUMN IF NOT EXISTS gender TEXT DEFAULT NULL")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_requests (
                    id                  SERIAL PRIMARY KEY,
                    discord_id          BIGINT NOT NULL,
                    discord_username    TEXT NOT NULL,
                    wiki_slug           TEXT NOT NULL UNIQUE,
                    wiki_title          TEXT NOT NULL,
                    submitted_at        BIGINT NOT NULL,
                    status              TEXT NOT NULL DEFAULT 'pending',
                    reviewed_at         BIGINT,
                    rejection_reason    TEXT
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_request_votes (
                    request_id      INT NOT NULL REFERENCES gacha_requests(id) ON DELETE CASCADE,
                    discord_id      BIGINT NOT NULL,
                    discord_username TEXT NOT NULL,
                    voted_at        BIGINT NOT NULL,
                    PRIMARY KEY (request_id, discord_id)
                )
            """)
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS gacha_request_bans (
                    discord_id  BIGINT PRIMARY KEY,
                    banned_at   BIGINT NOT NULL
                )
            """)
            await conn.execute("ALTER TABLE gacha_characters ADD COLUMN IF NOT EXISTS submitted_by_discord_id BIGINT DEFAULT NULL")
            await conn.execute("ALTER TABLE gacha_characters ADD COLUMN IF NOT EXISTS submitted_by_username TEXT DEFAULT NULL")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS override_rarity TEXT DEFAULT NULL")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS override_gender TEXT DEFAULT NULL")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS override_image_urls TEXT[] DEFAULT ARRAY[]::TEXT[]")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS thumbnail_url TEXT NOT NULL DEFAULT ''")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS override_faction TEXT DEFAULT NULL")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS wiki_extract TEXT NOT NULL DEFAULT ''")
            await conn.execute("ALTER TABLE gacha_requests ADD COLUMN IF NOT EXISTS wiki_lang TEXT NOT NULL DEFAULT 'en'")
