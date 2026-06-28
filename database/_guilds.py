import json
import time
import asyncio

from infra.redis_cache import cache_get, cache_set, cache_delete
from config.rules import (
    CIVIC_PARTICIPATION_ACTIVE_DAYS,
    GUILD_RANK_MIN_CITIZENS,
    GUILD_RANK_BRACKETS,
    GUILD_RANK_POLITBURO_MIN_CITIZENS,
    GUILD_RANK_POLITBURO_TOP_N,
)

_CACHE_TTL = 60

METRICS = ["happiness", "gdp", "civic", "literacy", "incarceration", "politburo"]

METRIC_LABELS = {
    "happiness":    "National Happiness Index",
    "gdp":          "GDP per Capita",
    "civic":        "Civic Participation Rate",
    "literacy":     "Literacy Rate",
    "incarceration": "Incarceration Rate",
    "politburo":    "Politburo Standing Committee",
}


def _bracket_for(citizens: int) -> str | None:
    if citizens < GUILD_RANK_MIN_CITIZENS:
        return None
    for name, lo, hi in GUILD_RANK_BRACKETS:
        if hi is None or citizens <= hi:
            return name
    return GUILD_RANK_BRACKETS[-1][0]


def _bracket_case_sql(citizens_expr: str) -> str:
    parts = []
    for name, lo, hi in GUILD_RANK_BRACKETS:
        if hi is None:
            parts.append(f"WHEN {citizens_expr} >= {lo} THEN '{name}'")
        else:
            parts.append(f"WHEN {citizens_expr} BETWEEN {lo} AND {hi} THEN '{name}'")
    return "CASE " + " ".join(parts) + " ELSE NULL END"


class GuildRankMixin:
    async def set_guild_name(self, guild_id: int, name: str):
        await self._pool.execute(
            """
            INSERT INTO guild_config (guild_id, guild_name)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE SET guild_name = EXCLUDED.guild_name
            """,
            guild_id, name,
        )

    async def set_leaderboard_visible(self, guild_id: int, visible: bool):
        await self._pool.execute(
            "UPDATE guild_config SET leaderboard_visible = $2 WHERE guild_id = $1",
            guild_id, visible,
        )
        await self._invalidate_guild_rank_caches(guild_id)

    async def _invalidate_guild_rank_caches(self, guild_id: int):
        from infra.redis_client import get_redis
        r = get_redis()
        brackets = [None, "Hamlet", "Village", "Town", "City", "Metropolis"]
        limits   = [10, 25, 100, 500]
        keys = [f"guildrank:{guild_id}"] + [
            f"guildlb:{metric}:{bracket}:{limit}"
            for metric in METRICS
            for bracket in brackets
            for limit in limits
        ]
        if keys:
            await r.delete(*keys)

    async def check_and_update_bracket(self, guild_id: int) -> str | None:
        async with self._pool.acquire() as conn:
            citizens = await conn.fetchval(
                "SELECT COUNT(*) FROM users WHERE guild_id = $1 AND has_chatted = 1",
                guild_id,
            )
            new_bracket = _bracket_for(int(citizens or 0))
            if new_bracket is None:
                return None
            old = await conn.fetchval(
                "SELECT guild_bracket FROM guild_config WHERE guild_id = $1", guild_id
            )
            if old == new_bracket:
                return None
            await conn.execute(
                "UPDATE guild_config SET guild_bracket = $2 WHERE guild_id = $1",
                guild_id, new_bracket,
            )
            return new_bracket

    async def is_leaderboard_visible(self, guild_id: int) -> bool:
        row = await self._pool.fetchrow(
            "SELECT leaderboard_visible FROM guild_config WHERE guild_id = $1",
            guild_id,
        )
        return bool(row and row["leaderboard_visible"])

    async def get_visible_guild_ids(self) -> set[int]:
        rows = await self._pool.fetch(
            "SELECT guild_id FROM guild_config WHERE leaderboard_visible = TRUE"
        )
        return {r["guild_id"] for r in rows}

    async def get_guild_rank(self, guild_id: int) -> dict | None:
        cache_key = f"guildrank:{guild_id}"
        raw = await cache_get(cache_key)
        if raw is not None:
            return json.loads(raw)

        now = int(time.time())
        active_cutoff = now - CIVIC_PARTICIPATION_ACTIVE_DAYS * 86400

        bracket_case = _bracket_case_sql("gs.citizens")

        row = await self._pool.fetchrow(
            f"""
            WITH guild_stats AS (
                SELECT
                    gc.guild_id,
                    gc.guild_name,
                    gc.leaderboard_visible,
                    COUNT(*) FILTER (WHERE u.has_chatted = 1) AS citizens,
                    COUNT(*) FILTER (WHERE u.last_active >= $1) AS active_citizens,
                    AVG(u.score) FILTER (WHERE u.has_chatted = 1) AS avg_score,
                    COALESCE(SUM(u.yuan) FILTER (WHERE u.has_chatted = 1), 0) AS total_yuan,
                    COALESCE(SUM(u.message_count) FILTER (WHERE u.has_chatted = 1), 0) AS total_messages,
                    COUNT(*) FILTER (WHERE u.score <= 610 AND u.has_chatted = 1) AS execution_count
                FROM guild_config gc
                LEFT JOIN users u ON u.guild_id = gc.guild_id
                GROUP BY gc.guild_id, gc.guild_name, gc.leaderboard_visible
            ),
            literacy_stats AS (
                SELECT u.guild_id,
                    (COUNT(DISTINCT u.user_id) FILTER (WHERE ach.user_id IS NOT NULL))::double precision
                    / NULLIF(COUNT(DISTINCT u.user_id), 0) AS literacy_rate
                FROM users u
                LEFT JOIN (SELECT DISTINCT user_id FROM achievements) ach ON ach.user_id = u.user_id
                WHERE u.has_chatted = 1
                GROUP BY u.guild_id
            ),
            guild_metrics AS (
                SELECT
                    gs.guild_id, gs.guild_name, gs.leaderboard_visible, gs.citizens,
                    {bracket_case} AS guild_bracket,
                    CASE WHEN gs.citizens >= $2 THEN COALESCE(gs.avg_score, 0) ELSE NULL END AS happiness,
                    CASE WHEN gs.citizens >= $2 THEN
                        CASE WHEN gs.citizens > 0 THEN gs.total_yuan::double precision / gs.citizens ELSE 0 END
                    ELSE NULL END AS gdp,
                    CASE WHEN gs.citizens >= $2 THEN
                        CASE WHEN gs.active_citizens > 0 THEN gs.total_messages::double precision / gs.active_citizens ELSE 0 END
                    ELSE NULL END AS civic,
                    CASE WHEN gs.citizens >= $2 THEN COALESCE(ls.literacy_rate, 0) ELSE NULL END AS literacy,
                    CASE WHEN gs.citizens >= $2 THEN
                        CASE WHEN gs.citizens > 0 THEN gs.execution_count::double precision / gs.citizens ELSE 0 END
                    ELSE NULL END AS incarceration
                FROM guild_stats gs
                LEFT JOIN literacy_stats ls ON ls.guild_id = gs.guild_id
            ),
            ranked AS (
                SELECT
                    guild_id, guild_name, leaderboard_visible, citizens, guild_bracket,
                    happiness, gdp, civic, literacy, incarceration,
                    RANK() OVER (ORDER BY happiness DESC NULLS LAST) AS rank_happiness,
                    RANK() OVER (ORDER BY gdp DESC NULLS LAST) AS rank_gdp,
                    RANK() OVER (ORDER BY civic DESC NULLS LAST) AS rank_civic,
                    RANK() OVER (ORDER BY literacy DESC NULLS LAST) AS rank_literacy,
                    RANK() OVER (ORDER BY incarceration ASC NULLS LAST) AS rank_incarceration,
                    COUNT(*) OVER () AS total_guilds,
                    RANK() OVER (PARTITION BY guild_bracket ORDER BY happiness DESC NULLS LAST) AS bracket_rank_happiness,
                    RANK() OVER (PARTITION BY guild_bracket ORDER BY gdp DESC NULLS LAST) AS bracket_rank_gdp,
                    RANK() OVER (PARTITION BY guild_bracket ORDER BY civic DESC NULLS LAST) AS bracket_rank_civic,
                    RANK() OVER (PARTITION BY guild_bracket ORDER BY literacy DESC NULLS LAST) AS bracket_rank_literacy,
                    RANK() OVER (PARTITION BY guild_bracket ORDER BY incarceration ASC NULLS LAST) AS bracket_rank_incarceration,
                    COUNT(*) OVER (PARTITION BY guild_bracket) AS total_guilds_in_bracket,
                    LAG(guild_name) OVER (ORDER BY happiness DESC NULLS LAST) AS rival_above_name,
                    LAG(happiness)  OVER (ORDER BY happiness DESC NULLS LAST) AS rival_above_happiness
                FROM guild_metrics
            )
            SELECT
                guild_id, guild_name, leaderboard_visible, citizens,
                happiness, gdp, civic, literacy, incarceration,
                rank_happiness, rank_gdp, rank_civic, rank_literacy, rank_incarceration,
                total_guilds,
                bracket_rank_happiness, bracket_rank_gdp, bracket_rank_civic,
                bracket_rank_literacy, bracket_rank_incarceration,
                total_guilds_in_bracket,
                rival_above_name,
                CASE WHEN rival_above_happiness IS NOT NULL AND happiness IS NOT NULL
                     THEN rival_above_happiness - happiness
                     ELSE NULL END AS rival_above_gap
            FROM ranked WHERE guild_id = $3
            """,
            active_cutoff, GUILD_RANK_MIN_CITIZENS, guild_id,
        )

        if not row:
            return None

        citizens = row["citizens"]
        bracket = _bracket_for(citizens)

        bracket_lo = bracket_hi = None
        for bname, lo, hi in GUILD_RANK_BRACKETS:
            if bname == bracket:
                bracket_lo, bracket_hi = lo, hi
                break

        async def _get_politburo():
            if citizens < GUILD_RANK_POLITBURO_MIN_CITIZENS:
                return None, None, None
            pb = await self._pool.fetchval(
                """
                SELECT AVG(score) FROM (
                    SELECT score FROM users
                    WHERE guild_id = $1 AND has_chatted = 1
                    ORDER BY score DESC LIMIT $2
                ) top
                """,
                guild_id, GUILD_RANK_POLITBURO_TOP_N,
            )
            if pb is None:
                return None, None, None

            async def _global_rank():
                return await self._pool.fetchval(
                    """
                    SELECT COUNT(*) + 1 FROM (
                        SELECT u.guild_id, AVG(top.score) AS pb_score
                        FROM guild_config gc
                        JOIN LATERAL (
                            SELECT score FROM users
                            WHERE guild_id = gc.guild_id AND has_chatted = 1
                            ORDER BY score DESC LIMIT $1
                        ) top ON true
                        JOIN users u ON u.guild_id = gc.guild_id
                        WHERE gc.guild_id != $2
                        GROUP BY u.guild_id
                        HAVING COUNT(*) FILTER (WHERE u.has_chatted = 1) >= $3
                    ) sub WHERE sub.pb_score > $4
                    """,
                    GUILD_RANK_POLITBURO_TOP_N, guild_id, GUILD_RANK_POLITBURO_MIN_CITIZENS, pb,
                )

            async def _bracket_rank():
                if bracket_lo is None:
                    return None
                having = (
                    f"COUNT(*) FILTER (WHERE u.has_chatted = 1) BETWEEN {bracket_lo} AND {bracket_hi}"
                    if bracket_hi is not None
                    else f"COUNT(*) FILTER (WHERE u.has_chatted = 1) >= {bracket_lo}"
                )
                return await self._pool.fetchval(
                    f"""
                    SELECT COUNT(*) + 1 FROM (
                        SELECT u.guild_id, AVG(top.score) AS pb_score
                        FROM guild_config gc
                        JOIN LATERAL (
                            SELECT score FROM users
                            WHERE guild_id = gc.guild_id AND has_chatted = 1
                            ORDER BY score DESC LIMIT $1
                        ) top ON true
                        JOIN users u ON u.guild_id = gc.guild_id
                        WHERE gc.guild_id != $2
                        GROUP BY u.guild_id
                        HAVING {having}
                    ) sub WHERE sub.pb_score > $3
                    """,
                    GUILD_RANK_POLITBURO_TOP_N, guild_id, pb,
                )

            rank_pb, bracket_rank_pb = await asyncio.gather(_global_rank(), _bracket_rank())
            return (
                float(pb),
                int(rank_pb or 1),
                int(bracket_rank_pb) if bracket_rank_pb is not None else None,
            )

        politburo, rank_politburo, bracket_rank_politburo = await _get_politburo()

        result = dict(row)
        result["bracket"] = bracket
        result["politburo"] = politburo
        result["rank_politburo"] = rank_politburo
        result["bracket_rank_politburo"] = bracket_rank_politburo
        if bracket is None:
            result["total_guilds_in_bracket"] = None
            for m in ("happiness", "gdp", "civic", "literacy", "incarceration"):
                result[f"bracket_rank_{m}"] = None

        await cache_set(cache_key, json.dumps(result), _CACHE_TTL)
        return result

    async def get_guild_leaderboard(self, metric: str, bracket: str | None = None, limit: int = 10) -> list[dict]:
        cache_key = f"guildlb:{metric}:{bracket}:{limit}"
        raw = await cache_get(cache_key)
        if raw is not None:
            return json.loads(raw)

        now = int(time.time())
        active_cutoff = now - CIVIC_PARTICIPATION_ACTIVE_DAYS * 86400

        if metric == "politburo":
            rows = await self._pool.fetch(
                """
                SELECT
                    gc.guild_id,
                    gc.guild_name,
                    COUNT(*) FILTER (WHERE u.has_chatted = 1) AS citizens,
                    AVG(top.score) AS value
                FROM guild_config gc
                JOIN LATERAL (
                    SELECT score FROM users
                    WHERE guild_id = gc.guild_id AND has_chatted = 1
                    ORDER BY score DESC
                    LIMIT $1
                ) top ON true
                JOIN users u ON u.guild_id = gc.guild_id
                GROUP BY gc.guild_id, gc.guild_name
                HAVING COUNT(*) FILTER (WHERE u.has_chatted = 1) >= $2
                ORDER BY value DESC NULLS LAST
                LIMIT $3
                """,
                GUILD_RANK_POLITBURO_TOP_N, GUILD_RANK_POLITBURO_MIN_CITIZENS, limit,
            )
        else:
            order = "ASC" if metric == "incarceration" else "DESC"
            value_expr = {
                "happiness":     "AVG(u.score) FILTER (WHERE u.has_chatted = 1)",
                "gdp":           "CASE WHEN COUNT(*) FILTER (WHERE u.has_chatted = 1) > 0 THEN SUM(u.yuan) FILTER (WHERE u.has_chatted = 1)::double precision / COUNT(*) FILTER (WHERE u.has_chatted = 1) ELSE 0 END",
                "civic":         f"CASE WHEN COUNT(*) FILTER (WHERE u.last_active >= {active_cutoff}) > 0 THEN (SUM(u.message_count) FILTER (WHERE u.has_chatted = 1))::double precision / COUNT(*) FILTER (WHERE u.last_active >= {active_cutoff}) ELSE 0 END",
                "literacy":      "(COUNT(*) FILTER (WHERE u.has_chatted = 1 AND a.achievement_count > 0))::double precision / NULLIF(COUNT(*) FILTER (WHERE u.has_chatted = 1), 0)",
                "incarceration": "(COUNT(*) FILTER (WHERE u.score <= 610 AND u.has_chatted = 1))::double precision / NULLIF(COUNT(*) FILTER (WHERE u.has_chatted = 1), 0)",
            }[metric]

            bracket_filter = ""
            if bracket and metric != "politburo":
                for name, lo, hi in GUILD_RANK_BRACKETS:
                    if name == bracket:
                        if hi is None:
                            bracket_filter = f"HAVING COUNT(*) FILTER (WHERE u.has_chatted = 1) >= {lo}"
                        else:
                            bracket_filter = f"HAVING COUNT(*) FILTER (WHERE u.has_chatted = 1) BETWEEN {lo} AND {hi}"
                        break
            else:
                bracket_filter = f"HAVING COUNT(*) FILTER (WHERE u.has_chatted = 1) >= {GUILD_RANK_MIN_CITIZENS}"

            literacy_join = ""
            if metric == "literacy":
                literacy_join = """
                LEFT JOIN (
                    SELECT user_id, COUNT(*) AS achievement_count FROM achievements GROUP BY user_id
                ) a ON a.user_id = u.user_id
                """

            rows = await self._pool.fetch(
                f"""
                SELECT
                    gc.guild_id,
                    gc.guild_name,
                    COUNT(*) FILTER (WHERE u.has_chatted = 1) AS citizens,
                    {value_expr} AS value
                FROM guild_config gc
                JOIN users u ON u.guild_id = gc.guild_id
                {literacy_join}
                GROUP BY gc.guild_id, gc.guild_name
                {bracket_filter}
                ORDER BY value {order} NULLS LAST
                LIMIT $1
                """,
                limit,
            )

        result = [dict(r) for r in rows]
        await cache_set(cache_key, json.dumps(result), _CACHE_TTL)
        return result

    async def snapshot_guild_daily_stats(self):
        today = int(time.time()) // 86400 * 86400

        await self._pool.execute(
            """
            WITH guild_base AS (
                SELECT
                    u.guild_id,
                    COALESCE(SUM(u.yuan) FILTER (WHERE u.has_chatted = 1), 0)            AS total_yuan,
                    COALESCE(AVG(u.score) FILTER (WHERE u.has_chatted = 1), 0)            AS avg_score,
                    COALESCE(SUM(u.message_count) FILTER (WHERE u.has_chatted = 1), 0)   AS total_messages,
                    COUNT(*) FILTER (WHERE u.has_chatted = 1)                             AS citizens,
                    COALESCE(
                        (COUNT(DISTINCT u.user_id) FILTER (WHERE u.has_chatted = 1 AND ach.user_id IS NOT NULL))::double precision
                        / NULLIF(COUNT(*) FILTER (WHERE u.has_chatted = 1), 0),
                        0
                    ) AS literacy_rate,
                    COALESCE(
                        (COUNT(*) FILTER (WHERE u.score <= 610 AND u.has_chatted = 1))::double precision
                        / NULLIF(COUNT(*) FILTER (WHERE u.has_chatted = 1), 0),
                        0
                    ) AS incarceration_rate
                FROM users u
                LEFT JOIN (SELECT DISTINCT user_id FROM achievements) ach ON ach.user_id = u.user_id
                GROUP BY u.guild_id
            ),
            politburo_scores AS (
                SELECT guild_id, AVG(score) AS politburo_score
                FROM (
                    SELECT guild_id, score,
                           ROW_NUMBER() OVER (PARTITION BY guild_id ORDER BY score DESC) AS rn
                    FROM users WHERE has_chatted = 1
                ) ranked
                WHERE rn <= $2
                GROUP BY guild_id
            )
            INSERT INTO guild_daily_snapshots (
                guild_id, day, total_yuan, avg_score, total_messages, citizens,
                literacy_rate, incarceration_rate, politburo_score
            )
            SELECT
                gb.guild_id, $1,
                gb.total_yuan, gb.avg_score, gb.total_messages, gb.citizens,
                gb.literacy_rate, gb.incarceration_rate,
                COALESCE(ps.politburo_score, 0)
            FROM guild_base gb
            LEFT JOIN politburo_scores ps ON ps.guild_id = gb.guild_id
            ON CONFLICT (guild_id, day) DO UPDATE SET
                total_yuan        = EXCLUDED.total_yuan,
                avg_score         = EXCLUDED.avg_score,
                total_messages    = EXCLUDED.total_messages,
                citizens          = EXCLUDED.citizens,
                literacy_rate     = EXCLUDED.literacy_rate,
                incarceration_rate = EXCLUDED.incarceration_rate,
                politburo_score   = EXCLUDED.politburo_score
            """,
            today, GUILD_RANK_POLITBURO_TOP_N,
        )

    async def get_guild_daily_snapshot(self, guild_id: int, days_ago: int) -> dict | None:
        day = int(time.time()) // 86400 * 86400 - days_ago * 86400
        row = await self._pool.fetchrow(
            "SELECT * FROM guild_daily_snapshots WHERE guild_id = $1 AND day = $2",
            guild_id, day,
        )
        return dict(row) if row else None

    async def get_guild_yuan_earned_window(self, guild_id: int, days: int) -> int:
        cutoff = int(time.time()) // 86400 * 86400 - days * 86400
        row = await self._pool.fetchrow(
            """
            SELECT
                (SELECT COALESCE(SUM(total_yuan_earned), 0) FROM users WHERE guild_id = $1) -
                COALESCE((
                    SELECT SUM(total_yuan) FROM guild_daily_snapshots
                    WHERE guild_id = $1 AND day = $2
                ), 0) AS earned
            """,
            guild_id, cutoff,
        )
        return max(0, int(row["earned"])) if row else 0
