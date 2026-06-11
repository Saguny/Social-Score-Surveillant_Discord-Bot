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
        web_consent       INTEGER DEFAULT 0,
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
    CREATE TABLE IF NOT EXISTS message_log (
        id         SERIAL PRIMARY KEY,
        guild_id   BIGINT,
        user_id    BIGINT,
        username   TEXT,
        content    TEXT,
        delta      DOUBLE PRECISION,
        reason     TEXT,
        timestamp  BIGINT
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
]


class Database:
    def __init__(self):
        self._dsn = os.getenv("DATABASE_URL", "")
        self._pool: asyncpg.Pool | None = None
        self._web_consent_cache: dict[int, bool] = {}
        self._pending_logs: list = []
        self._effect_cache: dict[tuple, tuple] = {}
        self._last_clean_effects: float = 0.0
        self._flush_task: asyncio.Task | None = None

    async def init(self):
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        await self._create_tables()

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
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                return await conn.fetchrow(
                    """
                    INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score,
                                       message_count, yuan, total_yuan_earned, has_chatted)
                    VALUES ($1, $2, 750.0, 750.0, 750.0, 1, $3, $3, 1)
                    ON CONFLICT (guild_id, user_id) DO UPDATE SET
                        message_count     = users.message_count + 1,
                        yuan              = users.yuan + $3,
                        total_yuan_earned = users.total_yuan_earned + $3,
                        has_chatted       = 1
                    RETURNING *
                    """,
                    guild_id, user_id, yuan,
                )

    def start_flush_task(self):
        self._flush_task = asyncio.create_task(self._flush_loop())

    async def stop_flush_task(self):
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
        await self._flush_logs()

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(10)
            await self._flush_logs()

    async def _flush_logs(self):
        if not self._pending_logs:
            return
        batch = self._pending_logs[:]
        self._pending_logs.clear()
        async with self._pool.acquire() as conn:
            await conn.executemany(
                "INSERT INTO message_log (guild_id, user_id, username, content, delta, reason, timestamp) VALUES ($1, $2, $3, $4, $5, $6, $7)",
                batch,
            )

    async def get_user(self, guild_id, user_id):
        await self.register_user(guild_id, user_id)
        return await self._pool.fetchrow(
            "SELECT * FROM users WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
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
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    "INSERT INTO users (guild_id, user_id, score, highest_score, lowest_score) VALUES ($1, $2, 750.0, 750.0, 750.0) ON CONFLICT (guild_id, user_id) DO NOTHING",
                    guild_id, user_id,
                )
                row = await conn.fetchrow(
                    "SELECT score FROM users WHERE guild_id = $1 AND user_id = $2",
                    guild_id, user_id,
                )
                old_score = row["score"]
                new_score = max(600.0, min(1300.0, old_score + delta))
                await conn.execute(
                    "UPDATE users SET score = $1, highest_score = GREATEST(highest_score, $1), lowest_score = LEAST(lowest_score, $1) WHERE guild_id = $2 AND user_id = $3",
                    new_score, guild_id, user_id,
                )
                await conn.execute(
                    "INSERT INTO score_history (guild_id, user_id, delta, reason, timestamp) VALUES ($1, $2, $3, $4, $5)",
                    guild_id, user_id, round(delta, 2), reason, int(time.time()),
                )
        return old_score, new_score

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

    async def get_surveillance_watchers(self, guild_id, target_id):
        rows = await self._pool.fetch(
            "SELECT user_id, metadata FROM active_effects WHERE guild_id = $1 AND effect_type = 'surveillance' AND expires_at > $2",
            guild_id, int(time.time()),
        )
        return [row["user_id"] for row in rows if json.loads(row["metadata"]).get("target_id") == target_id]

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

    async def get_web_consent(self, guild_id):
        if guild_id in self._web_consent_cache:
            return self._web_consent_cache[guild_id]
        async with self._pool.acquire() as conn:
            await self._ensure_guild(conn, guild_id)
            row = await conn.fetchrow(
                "SELECT web_consent FROM guild_config WHERE guild_id = $1", guild_id
            )
        result = bool(row["web_consent"]) if row else False
        self._web_consent_cache[guild_id] = result
        return result

    async def set_web_consent(self, guild_id, enabled, guild_name=""):
        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await self._ensure_guild(conn, guild_id)
                await conn.execute(
                    "UPDATE guild_config SET web_consent = $1, guild_name = $2 WHERE guild_id = $3",
                    1 if enabled else 0, guild_name, guild_id,
                )
        self._web_consent_cache[guild_id] = bool(enabled)

    def log_message(self, guild_id, user_id, username, content, delta, reason):
        self._pending_logs.append((guild_id, user_id, username, content, round(delta, 2), reason, int(time.time())))

    async def get_message_logs(self, guild_id, limit=100, before=None):
        if before:
            return await self._pool.fetch(
                "SELECT * FROM message_log WHERE guild_id = $1 AND id < $2 ORDER BY id DESC LIMIT $3",
                guild_id, before, limit,
            )
        return await self._pool.fetch(
            "SELECT * FROM message_log WHERE guild_id = $1 ORDER BY id DESC LIMIT $2",
            guild_id, limit,
        )

    async def get_guilds_with_consent(self):
        return await self._pool.fetch(
            "SELECT guild_id, guild_name FROM guild_config WHERE web_consent = 1"
        )

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
