import os
import time
import json
import asyncio
import asyncpg


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


class Database:
    def __init__(self):
        self._dsn = os.getenv("DATABASE_URL", "")
        self._pool: asyncpg.Pool | None = None
        self._effect_cache: dict[tuple, tuple] = {}
        self._last_clean_effects: float = 0.0

    async def init(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=40)
        await self._create_tables()
        await self._migrate()

    async def _migrate(self):
        async with self._pool.acquire() as conn:
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_checkin BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS checkin_streak INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_active BIGINT DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS propaganda_wins INTEGER DEFAULT 0")
            await conn.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS rank_entered_at BIGINT DEFAULT 0")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_score_history_timestamp ON score_history (timestamp)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_score_history_reason ON score_history (reason)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_active ON users (last_active)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_last_checkin ON users (last_checkin)")
            await conn.execute("CREATE INDEX IF NOT EXISTS idx_users_has_chatted_guild ON users (has_chatted, guild_id)")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS execution_channel_id BIGINT")
            await conn.execute("ALTER TABLE guild_config ADD COLUMN IF NOT EXISTS assign_rank_roles BOOLEAN NOT NULL DEFAULT TRUE")

    async def _create_tables(self):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for ddl in TABLES:
                    await conn.execute(ddl)

    async def _ensure_guild(self, conn, guild_id):
        await conn.execute(
            "INSERT INTO guild_config (guild_id) VALUES ($1) ON CONFLICT (guild_id) DO NOTHING",
            guild_id,
        )

    async def register_user(self, guild_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.execute(
                    "INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score) VALUES ($1, $2, 750.0, 750.0, 750.0) ON CONFLICT (guild_id, user_id) DO NOTHING",
                    guild_id, user_id,
                )

    async def register_guild_members(self, guild_id, user_ids):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.executemany(
                    "INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score) VALUES ($1, $2, 750.0, 750.0, 750.0) ON CONFLICT (guild_id, user_id) DO NOTHING",
                    [(guild_id, uid) for uid in user_ids],
                )

    async def tick_user(self, guild_id, user_id, yuan):
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                return await conn.fetchrow(
                    """
                    INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score,
                                       message_count, yuan, total_yuan_earned, has_chatted, last_active)
                    VALUES ($1, $2, 750.0, 750.0, 750.0, 1, $3, $3, 1, $4)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        message_count     = users.message_count + 1,
                        yuan              = users.yuan + $3,
                        total_yuan_earned = users.total_yuan_earned + $3,
                        has_chatted       = 1,
                        last_active       = $4
                    RETURNING *
                    """,
                    guild_id, user_id, yuan, now,
                )

    async def get_user(self, guild_id, user_id):
        await self.register_user(guild_id, user_id)
        return await self._pool.fetchrow(
            "SELECT * FROM users WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def confiscate_yuan(self, guild_id, user_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not row or row["yuan"] <= 0:
                    return 0
                total = row["yuan"]
                count = await conn.fetchval(
                    "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND user_id != $2",
                    guild_id, user_id,
                )
                if count and count > 0:
                    share = total // count
                    if share > 0:
                        await conn.execute(
                            "UPDATE users SET yuan = yuan + $3 WHERE guild_id = $1 AND user_id != $2",
                            guild_id, user_id, share,
                        )
                await conn.execute(
                    "UPDATE users SET yuan = 0 WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                return total

    async def get_condemned_users(self, guild_id):
        return await self._pool.fetch(
            "SELECT user_id, yuan FROM users WHERE guild_id = $1 AND score <= 610",
            guild_id,
        )

    async def adjust_yuan(self, guild_id, user_id, amount):
        await self._pool.execute(
            "UPDATE users SET yuan = GREATEST(0, yuan + $3) WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id, amount,
        )

    async def handle_rank_promotion(self, guild_id: int, user_id: int, new_rank_idx: int, yuan_amount: int) -> int:
        now = int(time.time())
        item_id = f"rank_promotion_{new_rank_idx}"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT rank_entered_at FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                prior = await conn.fetchval(
                    "SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = $3",
                    guild_id, user_id, item_id,
                )
                rank_entered_at = (row["rank_entered_at"] or 0) if row else 0
                eligible = prior == 0 or (now - rank_entered_at) >= 30 * 86400
                if eligible:
                    await conn.execute(
                        "UPDATE users SET yuan = GREATEST(0, yuan + $1), total_yuan_earned = total_yuan_earned + $1 WHERE guild_id = $2 AND user_id = $3",
                        yuan_amount, guild_id, user_id,
                    )
                    await conn.execute(
                        "INSERT INTO transactions (guild_id, user_id, item_id, cost, timestamp) VALUES ($1, $2, $3, $4, $5)",
                        guild_id, user_id, item_id, yuan_amount, now,
                    )
                await conn.execute(
                    "UPDATE users SET rank_entered_at = $1 WHERE guild_id = $2 AND user_id = $3",
                    now, guild_id, user_id,
                )
        return yuan_amount if eligible else 0

    async def set_rank_entered_at(self, guild_id: int, user_id: int):
        await self._pool.execute(
            "UPDATE users SET rank_entered_at = $1 WHERE guild_id = $2 AND user_id = $3",
            int(time.time()), guild_id, user_id,
        )

    async def consume_effect(self, guild_id: int, user_id: int, effect_type: str) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM active_effects WHERE id = (SELECT id FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4 LIMIT 1) RETURNING id",
            guild_id, user_id, effect_type, int(time.time()),
        )
        if row:
            self._effect_cache.pop((guild_id, user_id, effect_type), None)
        return row is not None

    async def get_execution_channel(self, guild_id):
        row = await self._pool.fetchrow(
            "SELECT execution_channel_id FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["execution_channel_id"] if row else None

    async def set_execution_channel(self, guild_id, channel_id):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET execution_channel_id = $2 WHERE guild_id = $1",
                guild_id, channel_id,
            )

    async def get_assign_rank_roles(self, guild_id) -> bool:
        row = await self._pool.fetchrow(
            "SELECT assign_rank_roles FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return row["assign_rank_roles"] if row else True

    async def set_assign_rank_roles(self, guild_id, enabled: bool):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            await conn.execute(
                "UPDATE guild_config SET assign_rank_roles = $2 WHERE guild_id = $1",
                guild_id, enabled,
            )

    async def mark_chatted(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET has_chatted = 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def increment_message_count(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET message_count = message_count + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def update_score(self, guild_id, user_id, delta, reason):
        now = int(time.time())
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    WITH old AS (
                        SELECT score FROM users WHERE guild_id = $1 AND user_id = $2
                    ), ensure AS (
                        INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score)
                        VALUES ($1, $2, 750.0, 750.0, 750.0)
                        ON CONFLICT DO NOTHING
                    ), updated AS (
                        UPDATE users SET
                            score         = GREATEST(600.0, LEAST(1300.0, score + $3)),
                            highest_score = GREATEST(highest_score, GREATEST(600.0, LEAST(1300.0, score + $3))),
                            lowest_score  = LEAST(lowest_score,     GREATEST(600.0, LEAST(1300.0, score + $3)))
                        WHERE guild_id = $1 AND user_id = $2
                        RETURNING score
                    ), history AS (
                        INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp)
                        SELECT $1, $2, ROUND($3::numeric, 2), $4, $5
                        FROM updated
                    )
                    SELECT
                        COALESCE((SELECT score FROM old), 750.0) AS old_score,
                        (SELECT score FROM updated)              AS new_score
                    """,
                    guild_id, user_id, delta, reason, now,
                )
        return row["old_score"], row["new_score"]

    async def add_yuan(self, guild_id, user_id, amount):
        await self._pool.execute(
            "UPDATE users SET yuan = yuan + $1, total_yuan_earned = total_yuan_earned + $1 WHERE guild_id = $2 AND user_id = $3",
            amount, guild_id, user_id,
        )

    async def spend_yuan(self, guild_id, user_id, amount):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not row or row["yuan"] < amount:
                    return False
                await conn.execute(
                    "UPDATE users SET yuan = yuan - $1, total_yuan_spent = total_yuan_spent + $1 WHERE guild_id = $2 AND user_id = $3",
                    amount, guild_id, user_id,
                )
        return True

    async def get_score_history(self, guild_id, user_id, limit=5):
        return await self._pool.fetch(
            "SELECT * FROM score_history WHERE guild_id = $1 AND user_id = $2 ORDER BY timestamp DESC LIMIT $3",
            guild_id, user_id, limit,
        )

    async def expunge_history(self, guild_id, user_id, count=5):
        rows = await self._pool.fetch(
            "SELECT id FROM score_history WHERE guild_id = $1 AND user_id = $2 ORDER BY timestamp DESC LIMIT $3",
            guild_id, user_id, count,
        )
        ids = [r["id"] for r in rows]
        if ids:
            await self._pool.execute("DELETE FROM score_history WHERE id = ANY($1::int[])", ids)

    async def add_effect(self, guild_id, user_id, effect_type, expires_at, metadata=None):
        await self._pool.execute(
            "INSERT INTO active_effects (guild_id, user_id, effect_type, metadata, expires_at) VALUES ($1, $2, $3, $4, $5)",
            guild_id, user_id, effect_type, json.dumps(metadata or {}), expires_at,
        )

    async def get_effect(self, guild_id, user_id, effect_type):
        now = time.time()
        cache_key = (guild_id, user_id, effect_type)
        if cache_key in self._effect_cache:
            cached_at, row = self._effect_cache[cache_key]
            if now - cached_at < 30 and (row is None or row["expires_at"] > int(now)):
                return row
        row = await self._pool.fetchrow(
            "SELECT * FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = $3 AND expires_at > $4",
            guild_id, user_id, effect_type, int(now),
        )
        self._effect_cache[cache_key] = (now, row)
        return row

    def invalidate_effect_cache(self, guild_id, user_id, effect_type):
        self._effect_cache.pop((guild_id, user_id, effect_type), None)

    async def consume_surveillance_for_target(self, guild_id: int, user_id: int, target_id: int) -> bool:
        rows = await self._pool.fetch(
            "SELECT id, metadata FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = 'surveillance' AND expires_at > $3",
            guild_id, user_id, int(time.time()),
        )
        effect_id = next(
            (row["id"] for row in rows if json.loads(row["metadata"]).get("target_id") == target_id),
            None,
        )
        if effect_id is None:
            return False
        await self._pool.execute("DELETE FROM active_effects WHERE id = $1", effect_id)
        return True

    async def get_surveillance_report(self, guild_id: int, target_id: int) -> dict:
        since = int(time.time()) - 30 * 86400
        async with self._pool.acquire() as conn:
            user = await conn.fetchrow(
                "SELECT score, yuan, highest_score, lowest_score, checkin_streak, propaganda_wins FROM users WHERE guild_id = $1 AND user_id = $2",
                guild_id, target_id,
            )
            history = await conn.fetch(
                "SELECT delta, reason, timestamp FROM score_history WHERE guild_id = $1 AND user_id = $2 AND timestamp > $3 ORDER BY timestamp DESC LIMIT 500",
                guild_id, target_id, since,
            )
        return {"user": user, "history": history}

    async def get_score_history_brief(self, guild_id: int, user_id: int, limit: int = 20):
        return await self._pool.fetch(
            "SELECT delta, reason, timestamp FROM score_history WHERE guild_id = $1 AND user_id = $2 ORDER BY timestamp DESC LIMIT $3",
            guild_id, user_id, limit,
        )

    async def get_last_attacker(self, guild_id: int, user_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT user_id FROM transactions WHERE guild_id = $1 AND target_user_id = $2 AND item_id IN ('report', 'denounce') ORDER BY timestamp DESC LIMIT 1",
            guild_id, user_id,
        )
        return row["user_id"] if row else None

    async def get_random_active_user(self, guild_id: int, exclude_id: int) -> int | None:
        row = await self._pool.fetchrow(
            "SELECT user_id FROM users WHERE guild_id = $1 AND user_id != $2 ORDER BY RANDOM() LIMIT 1",
            guild_id, exclude_id,
        )
        return row["user_id"] if row else None

    async def consume_investigation_bounty(self, guild_id: int, target_id: int) -> dict | None:
        rows = await self._pool.fetch(
            "SELECT id, metadata FROM active_effects WHERE guild_id = $1 AND user_id = $2 AND effect_type = 'investigation' AND expires_at > $3",
            guild_id, target_id, int(time.time()),
        )
        if not rows:
            return None
        row = rows[0]
        await self._pool.execute("DELETE FROM active_effects WHERE id = $1", row["id"])
        return json.loads(row["metadata"])

    async def add_fabricated_history(self, guild_id: int, user_id: int, reason: str):
        await self._pool.execute(
            "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, 0, $3, $4)",
            guild_id, user_id, f"[UNVERIFIED REPORT] {reason[:80]}", int(time.time()),
        )

    async def add_cosmetic_badge(self, guild_id: int, user_id: int, badge: str):
        await self._pool.execute(
            "INSERT INTO cosmetic_badges (guild_id, user_id, badge, purchased_at) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            guild_id, user_id, badge, int(time.time()),
        )

    async def get_cosmetic_badges(self, guild_id: int, user_id: int) -> list[str]:
        rows = await self._pool.fetch(
            "SELECT badge FROM cosmetic_badges WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )
        return [row["badge"] for row in rows]

    async def add_eternal_chairman(self, user_id: int):
        await self._pool.execute(
            "INSERT INTO eternal_chairmen (user_id, purchased_at) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id, int(time.time()),
        )

    async def get_all_eternal_chairmen(self) -> set[int]:
        rows = await self._pool.fetch("SELECT user_id FROM eternal_chairmen")
        return {row["user_id"] for row in rows}

    async def clean_expired_effects(self):
        now = time.time()
        if now - self._last_clean_effects < 60:
            return
        self._last_clean_effects = now
        await self._pool.execute("DELETE FROM active_effects WHERE expires_at <= $1", int(now))

    async def increment_report_counter(self, guild_id):
        await self._pool.execute(
            "UPDATE guild_config SET report_counter = report_counter + 1 WHERE guild_id = $1",
            guild_id,
        )
        row = await self._pool.fetchrow(
            "SELECT report_counter FROM guild_config WHERE guild_id = $1", guild_id
        )
        return row["report_counter"]

    async def log_transaction(self, guild_id, user_id, item_id, cost, target_user_id=None):
        await self._pool.execute(
            "INSERT INTO transactions (guild_id, user_id, item_id, cost, target_user_id, timestamp) VALUES ($1, $2, $3, $4, $5, $6)",
            guild_id, user_id, item_id, cost, target_user_id, int(time.time()),
        )

    async def increment_reported(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET times_reported = times_reported + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def increment_filed_reports(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET times_filed_reports = times_filed_reports + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def get_rehabilitation_count(self, guild_id, user_id):
        return await self._pool.fetchval(
            "SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND user_id = $2 AND item_id = 'rehabilitate'",
            guild_id, user_id,
        )

    async def get_leaderboard(self, guild_id):
        top = await self._pool.fetch(
            "SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score DESC LIMIT 3",
            guild_id,
        )
        bottom = await self._pool.fetch(
            "SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score ASC LIMIT 3",
            guild_id,
        )
        return {"top": top, "bottom": bottom}

    async def get_score_trend(self, guild_id, user_id, days):
        cutoff = int(time.time()) - (days * 86400)
        rows = await self._pool.fetch(
            "SELECT delta FROM score_history WHERE guild_id = $1 AND user_id = $2 AND timestamp > $3",
            guild_id, user_id, cutoff,
        )
        return round(sum(r["delta"] for r in rows), 2)

    async def get_guild_stats(self, guild_id):
        active = await self._pool.fetch(
            "SELECT * FROM users WHERE guild_id = $1 AND has_chatted = 1", guild_id
        )
        if not active:
            return {}
        total_yuan   = sum(u["yuan"] for u in active)
        avg_score    = sum(u["score"] for u in active) / len(active)
        top_score    = max(active, key=lambda u: u["score"])
        bottom_score = min(active, key=lambda u: u["score"])
        top_snitch   = max(active, key=lambda u: u["times_filed_reports"])
        total_reports = await self._pool.fetchval(
            "SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND item_id = 'report'",
            guild_id,
        )
        week_ago = int(time.time()) - 604800
        history = await self._pool.fetch(
            "SELECT user_id, delta FROM score_history WHERE guild_id = $1 AND timestamp > $2",
            guild_id, week_ago,
        )
        rises = {}
        falls = {}
        for h in history:
            uid, d = h["user_id"], h["delta"]
            if d > 0:
                rises[uid] = rises.get(uid, 0.0) + d
            elif d < 0:
                falls[uid] = falls.get(uid, 0.0) + d
        biggest_rise = max(rises.items(), key=lambda x: x[1]) if rises else None
        biggest_fall = min(falls.items(), key=lambda x: x[1]) if falls else None
        return {
            "total_yuan": total_yuan, "avg_score": avg_score,
            "active_count": len(active), "top_score": top_score,
            "bottom_score": bottom_score, "top_snitch": top_snitch,
            "total_reports": total_reports, "biggest_rise": biggest_rise,
            "biggest_fall": biggest_fall,
        }

    async def get_endorsement(self, guild_id, giver_id, target_id):
        return await self._pool.fetchrow(
            "SELECT * FROM endorsements WHERE guild_id = $1 AND giver_id = $2 AND target_id = $3",
            guild_id, giver_id, target_id,
        )

    async def set_endorsement(self, guild_id, giver_id, target_id, etype):
        await self._pool.execute(
            "INSERT INTO endorsements (guild_id, giver_id, target_id, type, timestamp) VALUES ($1, $2, $3, $4, $5) ON CONFLICT (guild_id, giver_id, target_id) DO UPDATE SET type = EXCLUDED.type, timestamp = EXCLUDED.timestamp",
            guild_id, giver_id, target_id, etype, int(time.time()),
        )

    async def update_social_counts(self, guild_id, target_id, uid, etype):
        recv_col  = "times_endorsed"     if etype == "endorse" else "times_rebuked"
        given_col = "endorsements_given" if etype == "endorse" else "rebukes_given"
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    f"UPDATE users SET {recv_col} = {recv_col} + 1 WHERE guild_id = $1 AND user_id = $2",
                    guild_id, target_id,
                )
                await conn.execute(
                    f"UPDATE users SET {given_col} = {given_col} + 1 WHERE guild_id = $1 AND user_id = $2",
                    guild_id, uid,
                )

    async def increment_items_bought(self, guild_id, user_id):
        await self._pool.execute(
            "UPDATE users SET items_bought = items_bought + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def get_confirm_threshold(self, guild_id):
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            row = await conn.fetchrow(
                "SELECT confirm_threshold FROM guild_config WHERE guild_id = $1", guild_id
            )
        return row["confirm_threshold"] if row else 3

    async def set_confirm_threshold(self, guild_id, n):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.execute(
                    "UPDATE guild_config SET confirm_threshold = $1 WHERE guild_id = $2", n, guild_id
                )

    async def create_fundraiser(self, guild_id, creator_id, description, goal):
        row = await self._pool.fetchrow(
            "INSERT INTO fundraisers (guild_id, creator_id, description, goal, created_at) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            guild_id, creator_id, description, goal, int(time.time()),
        )
        return row["id"]

    async def get_fundraiser(self, fundraiser_id):
        return await self._pool.fetchrow("SELECT * FROM fundraisers WHERE id = $1", fundraiser_id)

    async def set_fundraiser_message(self, fundraiser_id, channel_id, message_id):
        await self._pool.execute(
            "UPDATE fundraisers SET channel_id = $1, message_id = $2 WHERE id = $3",
            channel_id, message_id, fundraiser_id,
        )

    async def update_fundraiser_status(self, fundraiser_id, status):
        await self._pool.execute(
            "UPDATE fundraisers SET status = $1 WHERE id = $2", status, fundraiser_id
        )

    async def donate_to_fundraiser(self, fundraiser_id, guild_id, donor_id, amount):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO fundraiser_donations (fundraiser_id, guild_id, donor_id, amount, timestamp) VALUES ($1, $2, $3, $4, $5)",
                    fundraiser_id, guild_id, donor_id, amount, int(time.time()),
                )
                await conn.execute(
                    "UPDATE fundraisers SET raised = raised + $1 WHERE id = $2", amount, fundraiser_id
                )
                row = await conn.fetchrow(
                    "SELECT raised FROM fundraisers WHERE id = $1", fundraiser_id
                )
        return row["raised"]

    async def get_fundraiser_donations(self, fundraiser_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraiser_donations WHERE fundraiser_id = $1", fundraiser_id
        )

    async def add_fundraiser_vote(self, fundraiser_id, voter_id, vote):
        try:
            await self._pool.execute(
                "INSERT INTO fundraiser_votes (fundraiser_id, voter_id, vote) VALUES ($1, $2, $3)",
                fundraiser_id, voter_id, vote,
            )
            return True
        except asyncpg.UniqueViolationError:
            return False

    async def get_fundraiser_votes(self, fundraiser_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraiser_votes WHERE fundraiser_id = $1", fundraiser_id
        )

    async def get_active_fundraisers(self, guild_id):
        return await self._pool.fetch(
            "SELECT * FROM fundraisers WHERE guild_id = $1 AND status IN ('open', 'funded', 'voting') ORDER BY created_at DESC",
            guild_id,
        )

    async def reset_guild_db(self, guild_id):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                for table in ["users", "score_history", "active_effects", "transactions", "endorsements", "fundraiser_donations", "fundraisers"]:
                    await conn.execute(f"DELETE FROM {table} WHERE guild_id = $1", guild_id)
                await conn.execute("DELETE FROM fundraiser_votes WHERE fundraiser_id NOT IN (SELECT id FROM fundraisers)")
                await conn.execute("UPDATE guild_config SET report_counter = 0 WHERE guild_id = $1", guild_id)

    async def refund_fundraiser(self, fundraiser_id):
        donations = await self.get_fundraiser_donations(fundraiser_id)
        fr = await self.get_fundraiser(fundraiser_id)
        for d in donations:
            await self.add_yuan(fr["guild_id"], d["donor_id"], d["amount"])
        await self.update_fundraiser_status(fundraiser_id, "refunded")

    async def get_extended_leaderboard(self, guild_id):
        top_score = await self._pool.fetch(
            "SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score DESC LIMIT 3", guild_id,
        )
        bottom_score = await self._pool.fetch(
            "SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score ASC LIMIT 3", guild_id,
        )
        richest = await self._pool.fetch(
            "SELECT user_id, yuan FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY yuan DESC LIMIT 3", guild_id,
        )
        poorest = await self._pool.fetch(
            "SELECT user_id, yuan FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY yuan ASC LIMIT 3", guild_id,
        )
        most_messages = await self._pool.fetch(
            "SELECT user_id, message_count FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY message_count DESC LIMIT 3", guild_id,
        )
        most_endorsed = await self._pool.fetch(
            "SELECT user_id, times_endorsed FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_endorsed DESC LIMIT 3", guild_id,
        )
        most_rebuked = await self._pool.fetch(
            "SELECT user_id, times_rebuked FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_rebuked DESC LIMIT 3", guild_id,
        )
        top_snitches = await self._pool.fetch(
            "SELECT user_id, times_filed_reports FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_filed_reports DESC LIMIT 3", guild_id,
        )
        return {
            "top_score": top_score, "bottom_score": bottom_score,
            "richest": richest, "poorest": poorest,
            "most_messages": most_messages, "most_endorsed": most_endorsed,
            "most_rebuked": most_rebuked, "top_snitches": top_snitches,
        }

    async def do_checkin(self, guild_id, user_id):
        now = int(time.time())
        today_start = now - (now % 86400)
        yesterday_start = today_start - 86400
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    "SELECT last_checkin, checkin_streak, score FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                if not row:
                    return None
                if row["last_checkin"] >= today_start:
                    return {"already_checked_in": True}
                new_streak = (row["checkin_streak"] + 1) if row["last_checkin"] >= yesterday_start else 1
                yuan_reward = min(250 + (new_streak - 1) * 50, 750)
                score_delta = 0.2
                old_score = row["score"]
                new_score = min(1300.0, old_score + score_delta)
                await conn.execute(
                    """
                    UPDATE users SET
                        last_checkin   = $1,
                        checkin_streak = $2,
                        yuan           = yuan + $3,
                        total_yuan_earned = total_yuan_earned + $3,
                        score          = $4,
                        highest_score  = GREATEST(highest_score, $4)
                    WHERE guild_id = $5 AND user_id = $6
                    """,
                    now, new_streak, yuan_reward, new_score, guild_id, user_id,
                )
                await conn.execute(
                    "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, $3, $4, $5)",
                    guild_id, user_id, score_delta, f"daily check-in (streak: {new_streak})", now,
                )
        return {
            "already_checked_in": False, "streak": new_streak,
            "yuan_reward": yuan_reward, "score_delta": score_delta,
            "old_score": old_score, "new_score": new_score,
        }

    async def apply_score_decay(self):
        cutoff = int(time.time()) - (7 * 86400)
        await self._pool.execute(
            """
            UPDATE users SET
                score        = GREATEST(600.0, score - 0.1),
                lowest_score = LEAST(lowest_score, GREATEST(600.0, score - 0.1))
            WHERE has_chatted = 1
            AND last_active > 0
            AND last_active < $1
            AND score > 600.0
            """,
            cutoff,
        )

    async def create_propaganda_event(self, guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at):
        concludes_at = closes_at + 86400
        row = await self._pool.fetchrow(
            """
            INSERT INTO propaganda_events (guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at, concludes_at)
            VALUES ($1, $2, $3, $4, $5, $6) RETURNING id
            """,
            guild_id, mod_id, submit_channel_id, reveal_channel_id, closes_at, concludes_at,
        )
        return row["id"]

    async def get_open_propaganda_event(self, guild_id):
        return await self._pool.fetchrow(
            "SELECT * FROM propaganda_events WHERE guild_id = $1 AND status = 'open' AND closes_at > $2",
            guild_id, int(time.time()),
        )

    async def get_propaganda_events_ready_to_close(self, now):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_events WHERE status = 'open' AND closes_at <= $1", now,
        )

    async def get_propaganda_events_ready_to_conclude(self, now):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_events WHERE status = 'voting' AND concludes_at <= $1", now,
        )

    async def set_propaganda_event_status(self, event_id, status):
        await self._pool.execute(
            "UPDATE propaganda_events SET status = $1 WHERE id = $2", status, event_id,
        )

    async def add_propaganda_submission(self, event_id, guild_id, user_id, content):
        now = int(time.time())
        row = await self._pool.fetchrow(
            "INSERT INTO propaganda_submissions (event_id, guild_id, user_id, content, timestamp) VALUES ($1, $2, $3, $4, $5) RETURNING id",
            event_id, guild_id, user_id, content, now,
        )
        return row["id"]

    async def get_propaganda_submission_by_user(self, event_id, user_id):
        return await self._pool.fetchrow(
            "SELECT * FROM propaganda_submissions WHERE event_id = $1 AND user_id = $2",
            event_id, user_id,
        )

    async def is_propaganda_banned(self, event_id, user_id):
        row = await self._pool.fetchrow(
            "SELECT 1 FROM propaganda_event_bans WHERE event_id = $1 AND user_id = $2",
            event_id, user_id,
        )
        return row is not None

    async def ban_from_propaganda_event(self, event_id, guild_id, user_id, matched_content):
        await self._pool.execute(
            "INSERT INTO propaganda_event_bans (event_id, guild_id, user_id, matched_content) VALUES ($1, $2, $3, $4) ON CONFLICT DO NOTHING",
            event_id, guild_id, user_id, matched_content,
        )

    async def get_propaganda_submissions(self, event_id):
        return await self._pool.fetch(
            "SELECT * FROM propaganda_submissions WHERE event_id = $1 ORDER BY timestamp ASC",
            event_id,
        )

    async def set_submission_reveal_message(self, submission_id, message_id):
        await self._pool.execute(
            "UPDATE propaganda_submissions SET reveal_message_id = $1 WHERE id = $2",
            message_id, submission_id,
        )

    async def add_guild_decree(self, guild_id, user_id, content, vote_count):
        now = int(time.time())
        await self._pool.execute(
            "INSERT INTO guild_decrees (guild_id, user_id, content, won_at, vote_count) VALUES ($1, $2, $3, $4, $5)",
            guild_id, user_id, content, now, vote_count,
        )
        await self._pool.execute(
            "UPDATE users SET propaganda_wins = propaganda_wins + 1 WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        )

    async def get_guild_decrees(self, guild_id, limit=10):
        return await self._pool.fetch(
            "SELECT * FROM guild_decrees WHERE guild_id = $1 ORDER BY won_at DESC LIMIT $2",
            guild_id, limit,
        )

    async def get_global_stats(self):
        now      = int(time.time())
        day_ago  = now - 86400
        two_days = now - 172800
        week_ago = now - 604800

        (
            users_row,
            hist_row,
            misc_row,
            daily_7d,
            top_reasons,
            top_guild,
        ) = await asyncio.gather(
            self._pool.fetchrow("""
                SELECT
                    COUNT(*)                                                                        AS total_users,
                    COALESCE(SUM(message_count), 0)                                                AS total_messages,
                    COALESCE(SUM(yuan), 0)                                                         AS total_yuan,
                    COALESCE(SUM(total_yuan_earned), 0)                                            AS total_earned,
                    COALESCE(SUM(total_yuan_spent), 0)                                             AS total_spent,
                    COALESCE(SUM(items_bought), 0)                                                 AS total_items,
                    COALESCE(AVG(score) FILTER (WHERE has_chatted = 1), 750.0)                     AS avg_score,
                    COALESCE(MAX(highest_score), 750.0)                                            AS highest_score,
                    COALESCE(MIN(lowest_score), 750.0)                                             AS lowest_score,
                    COALESCE(AVG(message_count) FILTER (WHERE has_chatted = 1), 0)                 AS avg_msgs,
                    COALESCE(SUM(times_endorsed), 0)                                               AS endorsements,
                    COALESCE(SUM(times_rebuked), 0)                                                AS rebukes,
                    COALESCE(MAX(checkin_streak), 0)                                               AS highest_streak,
                    COUNT(*) FILTER (WHERE last_checkin >= $1)                                     AS checkins_today,
                    COUNT(*) FILTER (WHERE last_checkin >= $2 AND last_checkin < $1)               AS checkins_yday,
                    COUNT(*) FILTER (WHERE last_active >= $1)                                      AS dau,
                    COUNT(*) FILTER (WHERE last_active >= $3)                                      AS wau,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score < 650)                        AS t1,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 650 AND score < 700)       AS t2,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 700 AND score < 750)       AS t3,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 750 AND score < 800)       AS t4,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 800 AND score < 850)       AS t5,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 850 AND score < 900)       AS t6,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 900 AND score < 1000)      AS t7,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 1000)                      AS t8
                FROM users
            """, day_ago, two_days, week_ago),

            self._pool.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE delta > 0)                                              AS positive_events,
                    COUNT(*) FILTER (WHERE delta < 0)                                              AS negative_events,
                    COALESCE(AVG(delta), 0)                                                        AS avg_delta,
                    COUNT(*) FILTER (WHERE timestamp >= $1)                                        AS events_24h,
                    COUNT(*) FILTER (WHERE timestamp >= $2 AND timestamp < $1)                     AS events_prev_24h,
                    COUNT(*) FILTER (WHERE delta > 0 AND timestamp >= $1)                          AS pos_24h,
                    COUNT(*) FILTER (WHERE delta < 0 AND timestamp >= $1)                          AS neg_24h,
                    COUNT(*) FILTER (WHERE delta > 0 AND timestamp >= $2 AND timestamp < $1)       AS pos_prev_24h,
                    COUNT(*) FILTER (WHERE delta < 0 AND timestamp >= $2 AND timestamp < $1)       AS neg_prev_24h,
                    COALESCE(SUM(delta) FILTER (WHERE timestamp >= $3), 0)                         AS net_delta_7d
                FROM score_history
            """, day_ago, two_days, week_ago),

            self._pool.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM guild_config)                              AS total_guilds,
                    (SELECT COUNT(*) FROM guild_decrees)                             AS prop_winners,
                    (SELECT COUNT(*) FROM propaganda_events)                         AS prop_events,
                    (SELECT COUNT(*) FROM propaganda_submissions)                    AS prop_subs,
                    (SELECT COUNT(*) FROM active_effects WHERE expires_at > $1)      AS active_effects,
                    (SELECT COALESCE(SUM(raised), 0) FROM fundraisers)               AS fundraiser_yuan
            """, now),

            self._pool.fetch("""
                SELECT FLOOR(timestamp::float / 86400)::bigint AS day_num, COUNT(*) AS cnt
                FROM score_history WHERE timestamp >= $1
                GROUP BY day_num ORDER BY day_num
            """, week_ago),

            self._pool.fetch("""
                SELECT reason, COUNT(*) AS cnt, AVG(delta) AS avg_delta
                FROM score_history
                GROUP BY reason
                ORDER BY cnt DESC
                LIMIT 10
            """),

            self._pool.fetchrow("""
                SELECT u.guild_id, COALESCE(gc.guild_name, '') AS guild_name, SUM(u.message_count) AS total
                FROM users u
                LEFT JOIN guild_config gc ON u.guild_id = gc.guild_id
                GROUP BY u.guild_id, gc.guild_name
                ORDER BY total DESC
                LIMIT 1
            """),
        )

        return {
            "total_guilds":      int(misc_row["total_guilds"]),
            "total_users":       int(users_row["total_users"]),
            "total_messages":    int(users_row["total_messages"]),
            "total_yuan":        int(users_row["total_yuan"]),
            "total_earned":      int(users_row["total_earned"]),
            "total_spent":       int(users_row["total_spent"]),
            "total_items":       int(users_row["total_items"]),
            "avg_score":         round(float(users_row["avg_score"]), 2),
            "highest_score":     round(float(users_row["highest_score"]), 2),
            "lowest_score":      round(float(users_row["lowest_score"]), 2),
            "avg_msgs_per_user": round(float(users_row["avg_msgs"]), 1),
            "endorsements":      int(users_row["endorsements"]),
            "rebukes":           int(users_row["rebukes"]),
            "prop_winners":      int(misc_row["prop_winners"]),
            "prop_events":       int(misc_row["prop_events"]),
            "prop_subs":         int(misc_row["prop_subs"]),
            "active_effects":    int(misc_row["active_effects"]),
            "fundraiser_yuan":   int(misc_row["fundraiser_yuan"]),
            "highest_streak":    int(users_row["highest_streak"]),
            "checkins_today":    int(users_row["checkins_today"]),
            "checkins_yday":     int(users_row["checkins_yday"]),
            "dau":               int(users_row["dau"]),
            "wau":               int(users_row["wau"]),
            "positive_events":   int(hist_row["positive_events"]),
            "negative_events":   int(hist_row["negative_events"]),
            "avg_delta":         round(float(hist_row["avg_delta"]), 4),
            "events_24h":        int(hist_row["events_24h"]),
            "events_prev_24h":   int(hist_row["events_prev_24h"]),
            "pos_24h":           int(hist_row["pos_24h"]),
            "neg_24h":           int(hist_row["neg_24h"]),
            "pos_prev_24h":      int(hist_row["pos_prev_24h"]),
            "neg_prev_24h":      int(hist_row["neg_prev_24h"]),
            "net_delta_7d":      round(float(hist_row["net_delta_7d"]), 2),
            "daily_7d":          [[int(r["day_num"]), int(r["cnt"])] for r in daily_7d],
            "top_reasons":       [{"reason": r["reason"], "cnt": int(r["cnt"]), "avg_delta": round(float(r["avg_delta"]), 4)} for r in top_reasons],
            "most_active_guild": {
                "guild_id":   str(top_guild["guild_id"]) if top_guild else "",
                "guild_name": top_guild["guild_name"] if top_guild else "",
                "total":      int(top_guild["total"]) if top_guild else 0,
            },
            "score_dist": {
                "t1": int(users_row["t1"]), "t2": int(users_row["t2"]),
                "t3": int(users_row["t3"]), "t4": int(users_row["t4"]),
                "t5": int(users_row["t5"]), "t6": int(users_row["t6"]),
                "t7": int(users_row["t7"]), "t8": int(users_row["t8"]),
            },
        }

    async def get_poster_guilds(self):
        return await self._pool.fetch("SELECT guild_id, channel_id, last_slug FROM poster_config")

    async def enable_posters(self, guild_id, channel_id):
        await self._pool.execute(
            "INSERT INTO poster_config (guild_id, channel_id, last_slug) VALUES ($1, $2, '') "
            "ON CONFLICT (guild_id) DO UPDATE SET channel_id = EXCLUDED.channel_id",
            guild_id, channel_id,
        )

    async def disable_posters(self, guild_id):
        await self._pool.execute("DELETE FROM poster_config WHERE guild_id = $1", guild_id)

    async def set_poster_last(self, guild_id, slug):
        await self._pool.execute(
            "UPDATE poster_config SET last_slug = $1 WHERE guild_id = $2", slug, guild_id
        )

    async def log_poster_message(self, guild_id, channel_id, message_id):
        await self._pool.execute(
            "INSERT INTO poster_messages (guild_id, message_id, channel_id) VALUES ($1, $2, $3) "
            "ON CONFLICT DO NOTHING",
            guild_id, message_id, channel_id,
        )

    async def get_poster_message(self, guild_id, message_id):
        return await self._pool.fetchrow(
            "SELECT * FROM poster_messages WHERE guild_id = $1 AND message_id = $2",
            guild_id, message_id,
        )

    async def record_poster_reaction(self, message_id: int, user_id: int) -> bool:
        result = await self._pool.execute(
            "INSERT INTO poster_reactions (message_id, user_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            message_id, user_id,
        )
        return result == "INSERT 0 1"
