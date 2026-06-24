import time
import asyncio
import json

from infra.redis_cache import cache_get, cache_set


class StatsMixin:
    async def ping(self):
        return await self._pool.fetchval("SELECT 1")

    async def get_score_history(self, guild_id, user_id, limit=5):
        return await self._pool.fetch(
            "SELECT * FROM score_history WHERE guild_id = $1 AND user_id = $2 ORDER BY timestamp DESC LIMIT $3",
            guild_id, user_id, limit,
        )

    async def get_score_history_brief(self, guild_id: int, user_id: int, limit: int = 20):
        return await self._pool.fetch(
            "SELECT delta, reason, timestamp FROM score_history WHERE guild_id = $1 AND user_id = $2 ORDER BY timestamp DESC LIMIT $3",
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

    async def get_guild_user_rank(self, guild_id: int, user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COUNT(*) FILTER (WHERE score >= (SELECT score FROM users WHERE guild_id = $1 AND user_id = $2)) AS score_rank,
                COUNT(*) FILTER (WHERE yuan  >= (SELECT yuan  FROM users WHERE guild_id = $1 AND user_id = $2)) AS yuan_rank,
                COUNT(*) AS total
            FROM users
            WHERE guild_id = $1 AND has_chatted = 1
            """,
            guild_id, user_id,
        )
        return {
            "score_rank": int(row["score_rank"]),
            "yuan_rank":  int(row["yuan_rank"]),
            "total":      int(row["total"]),
        }

    async def get_score_trend(self, guild_id, user_id, days):
        cutoff = int(time.time()) - (days * 86400)
        rows = await self._pool.fetch(
            "SELECT delta FROM score_history WHERE guild_id = $1 AND user_id = $2 AND timestamp > $3",
            guild_id, user_id, cutoff,
        )
        return round(sum(r["delta"] for r in rows), 2)

    async def get_lifetime_score_stats(self, guild_id: int, user_id: int) -> dict:
        row = await self._pool.fetchrow(
            """
            SELECT
                COALESCE(SUM(delta) FILTER (WHERE delta > 0), 0) AS total_gained,
                COALESCE(SUM(delta) FILTER (WHERE delta < 0), 0) AS total_lost
            FROM score_history WHERE guild_id = $1 AND user_id = $2
            """,
            guild_id, user_id,
        )
        return {
            "total_gained": round(float(row["total_gained"]), 2),
            "total_lost":   round(float(row["total_lost"]),   2),
        }

    async def get_score_graph_data(self, guild_id: int, user_id: int, days: int = 30):
        cutoff = int(time.time()) - (days * 86400)
        rows, user = await asyncio.gather(
            self._pool.fetch(
                """
                SELECT FLOOR(timestamp::float / 86400)::bigint * 86400 AS day, SUM(delta) AS net_delta
                FROM score_history WHERE guild_id = $1 AND user_id = $2 AND timestamp > $3
                GROUP BY day ORDER BY day
                """,
                guild_id, user_id, cutoff,
            ),
            self._pool.fetchrow("SELECT score FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id),
        )
        return {"rows": rows, "current_score": float(user["score"]) if user else 750.0}

    async def get_yuan_graph_data(self, guild_id: int, user_id: int, days: int = 30):
        cutoff = int(time.time()) - (days * 86400)
        rows, user = await asyncio.gather(
            self._pool.fetch(
                "SELECT day, yuan FROM daily_yuan_snapshots WHERE guild_id = $1 AND user_id = $2 AND day > $3 ORDER BY day",
                guild_id, user_id, cutoff,
            ),
            self._pool.fetchrow("SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id),
        )
        return {"rows": rows, "current_yuan": int(user["yuan"]) if user else 0}

    async def get_daily_stats(self, guild_id: int, user_id: int) -> dict:
        now = int(time.time())
        today_start = now - (now % 86400)
        yesterday_start = today_start - 86400
        row, user = await asyncio.gather(
            self._pool.fetchrow(
                """
                SELECT
                    COALESCE(SUM(delta) FILTER (WHERE delta > 0 AND timestamp >= $3), 0)                         AS pos_today,
                    COALESCE(SUM(delta) FILTER (WHERE delta < 0 AND timestamp >= $3), 0)                         AS neg_today,
                    COALESCE(SUM(delta) FILTER (WHERE delta > 0 AND timestamp >= $4 AND timestamp < $3), 0)      AS pos_yesterday,
                    COALESCE(SUM(delta) FILTER (WHERE delta < 0 AND timestamp >= $4 AND timestamp < $3), 0)      AS neg_yesterday,
                    COUNT(*) FILTER (WHERE timestamp >= $3 AND reason ILIKE '%positive sentiment%')              AS pos_msgs_today,
                    COUNT(*) FILTER (WHERE timestamp >= $3 AND reason ILIKE '%civic participation%')             AS neutral_msgs_today,
                    COUNT(*) FILTER (
                        WHERE timestamp >= $3 AND (
                            reason ILIKE '%negative sentiment%'
                            OR reason ILIKE '%counter-revolutionary speech%'
                            OR reason ILIKE '%repeated transmission%'
                            OR reason ILIKE '%disruptive formatting%'
                        )
                    )                                                                                            AS neg_msgs_today
                FROM score_history WHERE guild_id = $1 AND user_id = $2
                """,
                guild_id, user_id, today_start, yesterday_start,
            ),
            self._pool.fetchrow("SELECT yuan, prev_day_yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id),
        )
        return {
            "pos_today":         round(float(row["pos_today"]), 2),
            "neg_today":         round(float(row["neg_today"]), 2),
            "pos_yesterday":     round(float(row["pos_yesterday"]), 2),
            "neg_yesterday":     round(float(row["neg_yesterday"]), 2),
            "pos_msgs_today":    row["pos_msgs_today"],
            "neg_msgs_today":    row["neg_msgs_today"],
            "neutral_msgs_today": row["neutral_msgs_today"],
            "yuan":              user["yuan"] if user else 0,
            "prev_day_yuan":     user["prev_day_yuan"] if user else 0,
        }

    async def get_leaderboard(self, guild_id):
        top, bottom = await asyncio.gather(
            self._pool.fetch("SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score ASC LIMIT 3", guild_id),
        )
        return {"top": top, "bottom": bottom}

    async def get_guild_daily_report(self, guild_id: int) -> dict:
        now = int(time.time())
        today_start = now - (now % 86400)
        yesterday_start = today_start - 86400
        row, agg = await asyncio.gather(
            self._pool.fetchrow(
                """
                SELECT
                    COALESCE(SUM(delta) FILTER (WHERE delta > 0 AND timestamp >= $2), 0)                         AS pos_today,
                    COALESCE(SUM(delta) FILTER (WHERE delta < 0 AND timestamp >= $2), 0)                         AS neg_today,
                    COALESCE(SUM(delta) FILTER (WHERE delta > 0 AND timestamp >= $3 AND timestamp < $2), 0)      AS pos_yesterday,
                    COALESCE(SUM(delta) FILTER (WHERE delta < 0 AND timestamp >= $3 AND timestamp < $2), 0)      AS neg_yesterday,
                    COUNT(*) FILTER (WHERE timestamp >= $2 AND reason ILIKE '%positive sentiment%')              AS pos_msgs_today,
                    COUNT(*) FILTER (WHERE timestamp >= $2 AND reason ILIKE '%civic participation%')             AS neutral_msgs_today,
                    COUNT(*) FILTER (
                        WHERE timestamp >= $2 AND (
                            reason ILIKE '%negative sentiment%'
                            OR reason ILIKE '%counter-revolutionary speech%'
                            OR reason ILIKE '%repeated transmission%'
                            OR reason ILIKE '%disruptive formatting%'
                        )
                    )                                                                                            AS neg_msgs_today,
                    COUNT(DISTINCT user_id) FILTER (WHERE timestamp >= $2)                                       AS active_today
                FROM score_history WHERE guild_id = $1
                """,
                guild_id, today_start, yesterday_start,
            ),
            self._pool.fetchrow(
                "SELECT COALESCE(SUM(yuan),0) AS yuan, COALESCE(SUM(prev_day_yuan),0) AS prev_day_yuan, COUNT(*) AS citizens FROM users WHERE guild_id = $1",
                guild_id,
            ),
        )
        return {
            "pos_today":          round(float(row["pos_today"]), 2),
            "neg_today":          round(float(row["neg_today"]), 2),
            "pos_yesterday":      round(float(row["pos_yesterday"]), 2),
            "neg_yesterday":      round(float(row["neg_yesterday"]), 2),
            "pos_msgs_today":     row["pos_msgs_today"],
            "neg_msgs_today":     row["neg_msgs_today"],
            "neutral_msgs_today": row["neutral_msgs_today"],
            "active_today":       row["active_today"],
            "yuan":               int(agg["yuan"]),
            "prev_day_yuan":      int(agg["prev_day_yuan"]),
            "citizens":           int(agg["citizens"]),
        }

    async def get_extended_leaderboard(self, guild_id):
        top_score, bottom_score, richest, poorest, most_messages, most_endorsed, most_rebuked, top_snitches = await asyncio.gather(
            self._pool.fetch("SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, score FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score ASC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, yuan FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY yuan DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, yuan FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY yuan ASC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, message_count FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY message_count DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, times_endorsed FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_endorsed DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, times_rebuked FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_rebuked DESC LIMIT 3", guild_id),
            self._pool.fetch("SELECT user_id, times_filed_reports FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_filed_reports DESC LIMIT 3", guild_id),
        )
        return {
            "top_score": top_score, "bottom_score": bottom_score,
            "richest": richest, "poorest": poorest,
            "most_messages": most_messages, "most_endorsed": most_endorsed,
            "most_rebuked": most_rebuked, "top_snitches": top_snitches,
        }

    _TIMELINE_RANGES = {
        "24h": (86400, 3600),
        "7d":  (7 * 86400, 86400),
        "30d": (30 * 86400, 86400),
        "90d": (90 * 86400, 86400),
    }

    async def get_global_timeline(self, range: str = "30d") -> dict:
        cutoff_secs, bucket_secs = self._TIMELINE_RANGES.get(range, self._TIMELINE_RANGES["30d"])
        cutoff = int(time.time()) - cutoff_secs

        score_rows, yuan_rows, portfolio_rows, join_rows = await asyncio.gather(
            self._pool.fetch(
                """
                SELECT
                    FLOOR(timestamp::float / $2)::bigint * $2 AS bucket,
                    SUM(delta) AS net_delta,
                    COUNT(*) FILTER (WHERE reason LIKE 'daily check-in%') AS checkins,
                    COUNT(*) FILTER (WHERE reason LIKE 'citizen endorse%') AS endorsements,
                    COUNT(*) FILTER (WHERE reason LIKE 'citizen rebuke%') AS rebukes,
                    COUNT(*) AS events,
                    COUNT(DISTINCT user_id) AS active_users
                FROM score_history
                WHERE timestamp > $1
                GROUP BY bucket ORDER BY bucket
                """,
                cutoff, bucket_secs,
            ),
            self._pool.fetch(
                """
                SELECT day AS bucket, SUM(yuan) AS total_yuan
                FROM daily_yuan_snapshots
                WHERE day > $1
                GROUP BY day ORDER BY day
                """,
                cutoff,
            ),
            self._pool.fetch(
                """
                WITH bucketed AS (
                    SELECT guild_id, user_id, value,
                           FLOOR(ts::float / $2)::bigint * $2 AS bucket,
                           ROW_NUMBER() OVER (PARTITION BY guild_id, user_id, FLOOR(ts::float / $2)::bigint ORDER BY ts DESC) AS rn
                    FROM portfolio_history
                    WHERE ts > $1
                )
                SELECT bucket, SUM(value) AS total_value
                FROM bucketed WHERE rn = 1
                GROUP BY bucket ORDER BY bucket
                """,
                cutoff, bucket_secs,
            ),
            self._pool.fetch(
                """
                SELECT
                    FLOOR(joined_at::float / $2)::bigint * $2 AS bucket,
                    COUNT(*) AS joins
                FROM guild_joins
                WHERE joined_at > $1
                GROUP BY bucket ORDER BY bucket
                """,
                cutoff, bucket_secs,
            ),
        )

        return {
            "score":     [[int(r["bucket"]), round(float(r["net_delta"]), 2)] for r in score_rows],
            "engagement": [
                {"bucket": int(r["bucket"]), "events": int(r["events"]), "checkins": int(r["checkins"]),
                 "endorsements": int(r["endorsements"]), "rebukes": int(r["rebukes"]),
                 "active_users": int(r["active_users"])}
                for r in score_rows
            ],
            "yuan":      [[int(r["bucket"]), int(r["total_yuan"])] for r in yuan_rows],
            "portfolio": [[int(r["bucket"]), int(r["total_value"])] for r in portfolio_rows],
            "joins":     [[int(r["bucket"]), int(r["joins"])] for r in join_rows],
        }

    async def get_global_user_rank(self, user_id: int) -> dict | None:
        cache_key = f"globalrank:user:v2:{user_id}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return json.loads(cached) if cached != "null" else None

        row = await self._pool.fetchrow(
            """
            WITH agg AS (
                SELECT u.user_id,
                       SUM(u.yuan) AS total_yuan,
                       AVG(u.score) AS avg_score,
                       COUNT(*) AS guild_count,
                       SUM(COALESCE(u.total_yuan_earned, 0)) AS total_earned
                FROM users u GROUP BY u.user_id
            ),
            with_prestige AS (
                SELECT agg.*,
                       COALESCE(pc.value, 0) AS prestige_level
                FROM agg
                LEFT JOIN user_counters pc ON pc.user_id = agg.user_id AND pc.counter_key = 'prestige_level'
            ),
            ranked AS (
                SELECT user_id, total_yuan, avg_score, guild_count, total_earned, prestige_level,
                       RANK() OVER (ORDER BY total_yuan DESC) AS balance_rank,
                       RANK() OVER (ORDER BY total_earned DESC) AS earned_rank,
                       RANK() OVER (ORDER BY avg_score DESC, prestige_level DESC) AS score_rank,
                       RANK() OVER (ORDER BY avg_score DESC, total_yuan DESC, prestige_level DESC) AS citizens_rank,
                       COUNT(*) OVER () AS total_citizens
                FROM with_prestige
            )
            SELECT * FROM ranked WHERE user_id = $1
            """,
            user_id,
        )
        if not row:
            await cache_set(cache_key, "null", ex=60)
            return None
        result = {
            "total_yuan":     int(row["total_yuan"]),
            "total_earned":   int(row["total_earned"]),
            "avg_score":      round(float(row["avg_score"]), 2),
            "guild_count":    int(row["guild_count"]),
            "balance_rank":   int(row["balance_rank"]),
            "earned_rank":    int(row["earned_rank"]),
            "score_rank":     int(row["score_rank"]),
            "citizens_rank":  int(row["citizens_rank"]),
            "total_citizens": int(row["total_citizens"]),
        }
        await cache_set(cache_key, json.dumps(result), ex=60)
        return result

    async def get_global_leaderboard(self, limit: int = 10) -> dict:
        cache_key = f"globaltop:leaderboard:{limit}"
        cached = await cache_get(cache_key)
        if cached is not None:
            data = json.loads(cached)
            return {
                "by_yuan":  [{"user_id": r["user_id"], "total_yuan": r["total_yuan"]} for r in data["by_yuan"]],
                "by_score": [{"user_id": r["user_id"], "avg_score": r["avg_score"]} for r in data["by_score"]],
            }

        by_yuan, by_score = await asyncio.gather(
            self._pool.fetch(
                "SELECT user_id, SUM(yuan) AS total_yuan FROM users GROUP BY user_id ORDER BY total_yuan DESC LIMIT $1",
                limit,
            ),
            self._pool.fetch(
                """
                WITH agg AS (
                    SELECT user_id, AVG(score) AS avg_score FROM users GROUP BY user_id
                )
                SELECT agg.user_id, agg.avg_score
                FROM agg
                LEFT JOIN user_counters pc ON pc.user_id = agg.user_id AND pc.counter_key = 'prestige_level'
                ORDER BY agg.avg_score DESC, COALESCE(pc.value, 0) DESC
                LIMIT $1
                """,
                limit,
            ),
        )
        result = {"by_yuan": by_yuan, "by_score": by_score}
        serializable = {
            "by_yuan":  [{"user_id": r["user_id"], "total_yuan": int(r["total_yuan"])} for r in by_yuan],
            "by_score": [{"user_id": r["user_id"], "avg_score": float(r["avg_score"])} for r in by_score],
        }
        await cache_set(cache_key, json.dumps(serializable), ex=60)
        return result

    async def get_global_yuan_earned_window(self, user_id: int, days: int | None = None) -> int:
        cache_key = f"globalrank:earned:{user_id}:{days}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return int(cached)

        if days is None:
            current_total = await self._pool.fetchval(
                "SELECT COALESCE(SUM(total_yuan_earned), 0) FROM users WHERE user_id = $1",
                user_id,
            )
            earned = int(current_total or 0)
        else:
            cutoff = int(time.time()) // 86400 * 86400 - (days * 86400)
            row = await self._pool.fetchrow(
                """
                WITH baseline AS (
                    SELECT total_yuan_earned FROM global_yuan_earned_snapshots
                    WHERE user_id = $1 AND day <= $2
                    ORDER BY day DESC LIMIT 1
                ),
                current AS (
                    SELECT COALESCE(SUM(total_yuan_earned), 0) AS total FROM users WHERE user_id = $1
                )
                SELECT current.total AS current_total, baseline.total_yuan_earned AS baseline_total
                FROM current LEFT JOIN baseline ON TRUE
                """,
                user_id, cutoff,
            )
            current_total = int(row["current_total"]) if row else 0
            baseline_total = int(row["baseline_total"]) if row and row["baseline_total"] is not None else 0
            earned = current_total - baseline_total

        await cache_set(cache_key, str(earned), ex=60)
        return earned

    async def get_global_yuan_earned_leaderboard(self, days: int | None = None, limit: int = 10) -> list[dict]:
        cache_key = f"globaltop:earned:{days}:{limit}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return json.loads(cached)

        if days is None:
            rows = await self._pool.fetch(
                "SELECT user_id, SUM(total_yuan_earned) AS earned FROM users GROUP BY user_id ORDER BY earned DESC LIMIT $1",
                limit,
            )
            result = [{"user_id": r["user_id"], "earned": int(r["earned"])} for r in rows]
        else:
            cutoff = int(time.time()) // 86400 * 86400 - (days * 86400)
            rows = await self._pool.fetch(
                """
                WITH baseline AS (
                    SELECT DISTINCT ON (user_id) user_id, total_yuan_earned AS baseline_total
                    FROM global_yuan_earned_snapshots
                    WHERE day <= $1
                    ORDER BY user_id, day DESC
                ),
                current AS (
                    SELECT user_id, SUM(total_yuan_earned) AS current_total
                    FROM users GROUP BY user_id
                )
                SELECT c.user_id, c.current_total - COALESCE(b.baseline_total, 0) AS earned
                FROM current c
                LEFT JOIN baseline b ON b.user_id = c.user_id
                ORDER BY earned DESC
                LIMIT $2
                """,
                cutoff, limit,
            )
            result = [{"user_id": r["user_id"], "earned": int(r["earned"])} for r in rows]

        await cache_set(cache_key, json.dumps(result), ex=60)
        return result

    async def get_global_citizens_leaderboard(self, limit: int = 10) -> list[dict]:
        cache_key = f"globaltop:citizens:{limit}"
        cached = await cache_get(cache_key)
        if cached is not None:
            return json.loads(cached)

        rows = await self._pool.fetch(
            """
            WITH agg AS (
                SELECT user_id, AVG(score) AS avg_score, SUM(yuan) AS total_yuan
                FROM users GROUP BY user_id
            )
            SELECT agg.user_id, agg.avg_score, agg.total_yuan
            FROM agg
            LEFT JOIN user_counters pc ON pc.user_id = agg.user_id AND pc.counter_key = 'prestige_level'
            ORDER BY agg.avg_score DESC, agg.total_yuan DESC, COALESCE(pc.value, 0) DESC
            LIMIT $1
            """,
            limit,
        )
        result = [
            {"user_id": r["user_id"], "avg_score": float(r["avg_score"]), "total_yuan": int(r["total_yuan"])}
            for r in rows
        ]
        await cache_set(cache_key, json.dumps(result), ex=60)
        return result

    async def get_recent_events(self, limit: int = 20):
        return await self._pool.fetch(
            "SELECT guild_id, user_id, delta, reason, timestamp FROM score_history ORDER BY timestamp DESC LIMIT $1",
            limit,
        )

    async def get_global_stats(self):
        now      = int(time.time())
        day_ago  = now - 86400
        two_days = now - 172800
        week_ago = now - 604800

        month_ago = now - 2592000

        (
            users_row,
            hist_totals_row,
            hist_window_row,
            misc_row,
            daily_7d,
            top_reasons,
            top_guild,
            markets_row,
            treasury_total,
        ) = await asyncio.gather(
            self._pool.fetchrow("""
                SELECT
                    COUNT(*)                                                                        AS total_users,
                    COALESCE(SUM(message_count), 0)                                                AS total_messages,
                    COALESCE(SUM(yuan), 0)                                                         AS total_yuan,
                    COALESCE(SUM(total_yuan_earned), 0)                                            AS total_earned,
                    COALESCE(SUM(total_yuan_spent), 0)                                             AS total_spent,
                    COALESCE(SUM(items_bought), 0)                                                 AS total_items,
                    COALESCE(SUM(lottery_played), 0)                                               AS lottery_played,
                    COALESCE(SUM(lottery_won), 0)                                                  AS lottery_won,
                    COALESCE(SUM(lottery_lost), 0)                                                 AS lottery_lost,
                    COALESCE(SUM(lottery_net), 0)                                                  AS lottery_net,
                    COALESCE(AVG(score) FILTER (WHERE has_chatted = 1), 750.0)                     AS avg_score,
                    COALESCE(MAX(highest_score), 750.0)                                            AS highest_score,
                    COALESCE(MIN(lowest_score), 750.0)                                             AS lowest_score,
                    COALESCE(MAX(yuan), 0)                                                         AS highest_yuan,
                    COALESCE(AVG(message_count) FILTER (WHERE has_chatted = 1), 0)                 AS avg_msgs,
                    COALESCE(SUM(times_endorsed), 0)                                               AS endorsements,
                    COALESCE(SUM(times_rebuked), 0)                                                AS rebukes,
                    COALESCE(MAX(longest_checkin_streak), 0)                                       AS highest_streak,
                    COUNT(*) FILTER (WHERE last_checkin >= $1)                                     AS checkins_today,
                    COUNT(*) FILTER (WHERE last_checkin >= $2 AND last_checkin < $1)               AS checkins_yday,
                    COUNT(*) FILTER (WHERE last_active >= $1)                                      AS dau,
                    COUNT(*) FILTER (WHERE last_active >= $3)                                      AS wau,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score < 700)                        AS t1,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 700  AND score < 775)      AS t2,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 775  AND score < 850)      AS t3,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 850  AND score < 925)      AS t4,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 925  AND score < 1000)     AS t5,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 1000 AND score < 1100)     AS t6,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 1100 AND score < 1200)     AS t7,
                    COUNT(*) FILTER (WHERE has_chatted = 1 AND score >= 1200)                      AS t8
                FROM users
            """, day_ago, two_days, week_ago),

            self._pool.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE delta > 0)                                              AS positive_events,
                    COUNT(*) FILTER (WHERE delta < 0)                                              AS negative_events,
                    COALESCE(AVG(delta), 0)                                                        AS avg_delta
                FROM score_history
            """),

            self._pool.fetchrow("""
                SELECT
                    COUNT(*) FILTER (WHERE timestamp >= $1)                                        AS events_24h,
                    COUNT(*) FILTER (WHERE timestamp >= $2 AND timestamp < $1)                     AS events_prev_24h,
                    COUNT(*) FILTER (WHERE delta > 0 AND timestamp >= $1)                          AS pos_24h,
                    COUNT(*) FILTER (WHERE delta < 0 AND timestamp >= $1)                          AS neg_24h,
                    COUNT(*) FILTER (WHERE delta > 0 AND timestamp >= $2 AND timestamp < $1)       AS pos_prev_24h,
                    COUNT(*) FILTER (WHERE delta < 0 AND timestamp >= $2 AND timestamp < $1)       AS neg_prev_24h,
                    COALESCE(SUM(delta) FILTER (WHERE timestamp >= $3), 0)                         AS net_delta_7d
                FROM score_history
                WHERE timestamp >= $3
            """, day_ago, two_days, week_ago),

            self._pool.fetchrow("""
                SELECT
                    (SELECT COUNT(*) FROM guild_config)                              AS total_guilds,
                    (SELECT COUNT(*) FROM guild_decrees)                             AS prop_winners,
                    (SELECT COUNT(*) FROM propaganda_events)                         AS prop_events,
                    (SELECT COUNT(*) FROM propaganda_submissions)                    AS prop_subs,
                    (SELECT COUNT(*) FROM active_effects WHERE expires_at > $1)      AS active_effects,
                    (SELECT COALESCE(SUM(raised), 0) FROM fundraisers)               AS fundraiser_yuan,
                    (SELECT COUNT(*) FROM topgg_votes)                               AS total_votes
            """, now),

            self._pool.fetch("""
                SELECT FLOOR(timestamp::float / 86400)::bigint AS day_num, COUNT(*) AS cnt
                FROM score_history WHERE timestamp >= $1
                GROUP BY day_num ORDER BY day_num
            """, week_ago),

            self._pool.fetch("""
                SELECT reason, COUNT(*) AS cnt, AVG(delta) AS avg_delta
                FROM score_history
                WHERE timestamp >= $1
                GROUP BY reason
                ORDER BY cnt DESC
                LIMIT 10
            """, month_ago),

            self._pool.fetchrow("""
                SELECT u.guild_id, COALESCE(gc.guild_name, '') AS guild_name, SUM(u.message_count) AS total
                FROM users u
                LEFT JOIN guild_config gc ON u.guild_id = gc.guild_id
                GROUP BY u.guild_id, gc.guild_name
                ORDER BY total DESC
                LIMIT 1
            """),

            self._pool.fetchrow("""
                SELECT
                    COALESCE((
                        SELECT SUM(p.shares * s.price)
                        FROM portfolios p
                        JOIN stocks s ON p.ticker = s.ticker
                    ), 0) AS yuan_in_stocks,
                    COALESCE((SELECT SUM(cost) FROM turbo_positions WHERE status = 'open'), 0) AS yuan_in_turbos,
                    COALESCE((SELECT SUM(turbo_knocked) FROM users WHERE turbo_knocked > 0), 0) AS total_knockouts,
                    COALESCE((SELECT SUM(stock_trades) FROM users WHERE stock_trades > 0), 0) AS total_stock_trades
            """),
            self._pool.fetchval("SELECT total FROM bureau_treasury WHERE id = 1"),
        )

        return {
            "total_guilds":      int(misc_row["total_guilds"]),
            "total_users":       int(users_row["total_users"]),
            "total_messages":    int(users_row["total_messages"]),
            "total_yuan":        int(users_row["total_yuan"]),
            "total_earned":      int(users_row["total_earned"]),
            "total_spent":       int(users_row["total_spent"]),
            "total_items":       int(users_row["total_items"]),
            "lottery_played":    int(users_row["lottery_played"]),
            "lottery_won":       int(users_row["lottery_won"]),
            "lottery_lost":      int(users_row["lottery_lost"]),
            "lottery_net":       int(users_row["lottery_net"]),
            "avg_score":         round(float(users_row["avg_score"]), 2),
            "highest_score":     round(float(users_row["highest_score"]), 2),
            "lowest_score":      round(float(users_row["lowest_score"]), 2),
            "highest_yuan":      int(users_row["highest_yuan"]),
            "avg_msgs_per_user": round(float(users_row["avg_msgs"]), 1),
            "endorsements":      int(users_row["endorsements"]),
            "rebukes":           int(users_row["rebukes"]),
            "prop_winners":      int(misc_row["prop_winners"]),
            "prop_events":       int(misc_row["prop_events"]),
            "prop_subs":         int(misc_row["prop_subs"]),
            "active_effects":    int(misc_row["active_effects"]),
            "fundraiser_yuan":   int(misc_row["fundraiser_yuan"]),
            "total_votes":       int(misc_row["total_votes"]),
            "highest_streak":    int(users_row["highest_streak"]),
            "checkins_today":    int(users_row["checkins_today"]),
            "checkins_yday":     int(users_row["checkins_yday"]),
            "dau":               int(users_row["dau"]),
            "wau":               int(users_row["wau"]),
            "positive_events":   int(hist_totals_row["positive_events"]),
            "negative_events":   int(hist_totals_row["negative_events"]),
            "avg_delta":         round(float(hist_totals_row["avg_delta"]), 4),
            "events_24h":        int(hist_window_row["events_24h"]),
            "events_prev_24h":   int(hist_window_row["events_prev_24h"]),
            "pos_24h":           int(hist_window_row["pos_24h"]),
            "neg_24h":           int(hist_window_row["neg_24h"]),
            "pos_prev_24h":      int(hist_window_row["pos_prev_24h"]),
            "neg_prev_24h":      int(hist_window_row["neg_prev_24h"]),
            "net_delta_7d":      round(float(hist_window_row["net_delta_7d"]), 2),
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
            "yuan_in_stocks":     int(markets_row["yuan_in_stocks"])     if markets_row else 0,
            "yuan_in_turbos":     int(markets_row["yuan_in_turbos"])     if markets_row else 0,
            "total_knockouts":    int(markets_row["total_knockouts"])    if markets_row else 0,
            "total_stock_trades": int(markets_row["total_stock_trades"]) if markets_row else 0,
            "treasury_total":     int(treasury_total) if treasury_total else 0,
        }
