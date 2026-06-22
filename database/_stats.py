import time
import asyncio


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

    async def get_score_trend(self, guild_id, user_id, days):
        cutoff = int(time.time()) - (days * 86400)
        rows = await self._pool.fetch(
            "SELECT delta FROM score_history WHERE guild_id = $1 AND user_id = $2 AND timestamp > $3",
            guild_id, user_id, cutoff,
        )
        return round(sum(r["delta"] for r in rows), 2)

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
        return await self._pool.fetch(
            "SELECT day, yuan FROM daily_yuan_snapshots WHERE guild_id = $1 AND user_id = $2 AND day > $3 ORDER BY day",
            guild_id, user_id, cutoff,
        )

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

    async def get_guild_stats(self, guild_id):
        week_ago = int(time.time()) - 604800
        agg, top_score, bottom_score, top_snitch, total_reports, rise_row, fall_row = await asyncio.gather(
            self._pool.fetchrow(
                "SELECT COUNT(*) AS cnt, COALESCE(SUM(yuan),0) AS total_yuan, COALESCE(AVG(score),750.0) AS avg_score FROM users WHERE guild_id = $1 AND has_chatted = 1",
                guild_id,
            ),
            self._pool.fetchrow("SELECT * FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score DESC LIMIT 1", guild_id),
            self._pool.fetchrow("SELECT * FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY score ASC LIMIT 1", guild_id),
            self._pool.fetchrow("SELECT * FROM users WHERE guild_id = $1 AND has_chatted = 1 ORDER BY times_filed_reports DESC LIMIT 1", guild_id),
            self._pool.fetchval("SELECT COUNT(*) FROM transactions WHERE guild_id = $1 AND item_id = 'report'", guild_id),
            self._pool.fetchrow(
                "SELECT user_id, SUM(delta) AS net FROM score_history WHERE guild_id = $1 AND timestamp > $2 AND delta > 0 GROUP BY user_id ORDER BY net DESC LIMIT 1",
                guild_id, week_ago,
            ),
            self._pool.fetchrow(
                "SELECT user_id, SUM(delta) AS net FROM score_history WHERE guild_id = $1 AND timestamp > $2 AND delta < 0 GROUP BY user_id ORDER BY net ASC LIMIT 1",
                guild_id, week_ago,
            ),
        )
        if not agg or agg["cnt"] == 0:
            return {}
        return {
            "total_yuan":    int(agg["total_yuan"]),
            "avg_score":     float(agg["avg_score"]),
            "active_count":  int(agg["cnt"]),
            "top_score":     top_score,
            "bottom_score":  bottom_score,
            "top_snitch":    top_snitch,
            "total_reports": total_reports or 0,
            "biggest_rise":  (rise_row["user_id"], float(rise_row["net"])) if rise_row else None,
            "biggest_fall":  (fall_row["user_id"], float(fall_row["net"])) if fall_row else None,
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

        (
            users_row,
            hist_row,
            misc_row,
            daily_7d,
            top_reasons,
            top_guild,
            markets_row,
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
            "yuan_in_stocks":     int(markets_row["yuan_in_stocks"])     if markets_row else 0,
            "yuan_in_turbos":     int(markets_row["yuan_in_turbos"])     if markets_row else 0,
            "total_knockouts":    int(markets_row["total_knockouts"])    if markets_row else 0,
            "total_stock_trades": int(markets_row["total_stock_trades"]) if markets_row else 0,
        }
