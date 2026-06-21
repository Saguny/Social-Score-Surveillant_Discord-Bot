import os
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
    CREATE TABLE IF NOT EXISTS cosmetic_badges (
        guild_id     BIGINT,
        user_id      BIGINT,
        badge        TEXT,
        purchased_at BIGINT,
        PRIMARY KEY (guild_id, user_id, badge)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS eternal_chairmen (
        user_id      BIGINT PRIMARY KEY,
        purchased_at BIGINT
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
):
    def __init__(self):
        self._dsn = os.getenv("DATABASE_URL", "")
        self._pool: asyncpg.Pool | None = None
        self._effect_cache: dict[tuple, tuple] = {}
        self._last_clean_effects: float = 0.0

    async def init(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=40)
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
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_user   ON transactions (guild_id, user_id, item_id)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_transactions_target ON transactions (guild_id, target_user_id, item_id, timestamp DESC)")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS vote_reminders (
                    user_id   BIGINT PRIMARY KEY,
                    remind_at BIGINT NOT NULL
                )
            """)
            await conn.execute("ALTER TABLE cosmetic_badges ADD COLUMN IF NOT EXISTS expires_at BIGINT")
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS topgg_votes (
                    user_id  BIGINT NOT NULL,
                    voted_at BIGINT NOT NULL
                )
            """)
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_topgg_votes_voted_at ON topgg_votes (voted_at)")
