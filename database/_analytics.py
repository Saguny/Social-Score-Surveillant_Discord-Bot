import time
import asyncio


class AnalyticsMixin:
    async def log_command(
        self,
        guild_id: int,
        user_id: int,
        command_name: str,
        subcommand: str | None,
        execution_time_ms: int,
        success: bool,
        error_code: str | None = None,
    ) -> None:
        try:
            await self._pool.execute(
                """
                INSERT INTO command_analytics
                    (timestamp, guild_id, user_id, command_name, subcommand, execution_time_ms, success, error_code)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                """,
                int(time.time()), guild_id, user_id, command_name,
                subcommand, execution_time_ms, success, error_code,
            )
        except Exception as e:
            print(f"[analytics] log_command failed: {e!r}")

    async def get_command_stats(self, range_: str = "7d") -> dict:
        now = int(time.time())
        cutoffs = {
            "24h": now - 86400,
            "7d":  now - 7 * 86400,
            "30d": now - 30 * 86400,
            "all": 0,
        }
        since = cutoffs.get(range_, cutoffs["7d"])
        today_start = (now // 86400) * 86400
        day_ago = now - 86400

        (
            top_cmds,
            unique_users,
            usage_per_day,
            usage_per_hour,
            avg_exec,
            per_cmd_rates,
            newest,
            all_cmds,
            totals,
        ) = await asyncio.gather(
            self._pool.fetch(
                """
                SELECT command_name, COUNT(*) AS uses
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY command_name ORDER BY uses DESC LIMIT 15
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT command_name, COUNT(DISTINCT user_id) AS unique_users
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY command_name ORDER BY unique_users DESC LIMIT 15
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT (timestamp / 86400 * 86400) AS day, COUNT(*) AS uses
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY day ORDER BY day
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT EXTRACT(HOUR FROM to_timestamp(timestamp))::int AS hour, COUNT(*) AS uses
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY hour ORDER BY hour
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT command_name,
                       ROUND(AVG(execution_time_ms)::numeric, 1) AS avg_ms
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY command_name ORDER BY avg_ms DESC LIMIT 15
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT command_name,
                       COUNT(*) AS total,
                       COUNT(*) FILTER (WHERE success) AS successes,
                       COUNT(*) FILTER (WHERE NOT success) AS errors,
                       ROUND(
                           COUNT(*) FILTER (WHERE NOT success)::numeric
                           / NULLIF(COUNT(*), 0) * 100, 2
                       ) AS error_pct,
                       ROUND(
                           COUNT(*) FILTER (WHERE success)::numeric
                           / NULLIF(COUNT(*), 0) * 100, 2
                       ) AS success_pct
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY command_name ORDER BY total DESC LIMIT 15
                """,
                since,
            ),
            self._pool.fetch(
                """
                SELECT timestamp, user_id, command_name, subcommand, execution_time_ms, success, error_code
                FROM command_analytics
                ORDER BY timestamp DESC LIMIT 10
                """,
            ),
            self._pool.fetch(
                """
                SELECT command_name,
                       COALESCE(subcommand, '') AS subcommand,
                       COUNT(*) AS uses,
                       COUNT(DISTINCT user_id) AS unique_users
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                GROUP BY command_name, subcommand
                ORDER BY uses DESC
                """,
                since,
            ),
            self._pool.fetchrow(
                """
                SELECT
                    COUNT(*)                                          AS total_executions,
                    COUNT(*) FILTER (WHERE timestamp >= $2)           AS executions_today,
                    COUNT(*) FILTER (WHERE timestamp >= $3)           AS executions_24h,
                    COUNT(DISTINCT user_id)                           AS unique_users,
                    ROUND(AVG(execution_time_ms)::numeric, 1)        AS avg_execution_time_ms,
                    ROUND(
                        COUNT(*) FILTER (WHERE success)::numeric
                        / NULLIF(COUNT(*), 0) * 100, 2
                    )                                                 AS overall_success_rate
                FROM command_analytics
                WHERE ($1 = 0 OR timestamp >= $1)
                """,
                since, today_start, day_ago,
            ),
        )

        return {
            "top_commands": [
                {"command": r["command_name"], "uses": r["uses"]}
                for r in top_cmds
            ],
            "unique_users_per_command": [
                {"command": r["command_name"], "unique_users": r["unique_users"]}
                for r in unique_users
            ],
            "usage_per_day": [
                {"day": int(r["day"]), "uses": r["uses"]}
                for r in usage_per_day
            ],
            "usage_per_hour": [
                {"hour": r["hour"], "uses": r["uses"]}
                for r in usage_per_hour
            ],
            "average_execution_time": [
                {"command": r["command_name"], "avg_ms": float(r["avg_ms"] or 0)}
                for r in avg_exec
            ],
            "per_command_rates": [
                {
                    "command":     r["command_name"],
                    "total":       r["total"],
                    "successes":   r["successes"],
                    "errors":      r["errors"],
                    "error_pct":   float(r["error_pct"]) if r["error_pct"] is not None else 0.0,
                    "success_pct": float(r["success_pct"]) if r["success_pct"] is not None else 100.0,
                }
                for r in per_cmd_rates
            ],
            "newest_commands": [
                {
                    "timestamp":         r["timestamp"],
                    "user_id":           r["user_id"],
                    "command_name":      r["command_name"],
                    "subcommand":        r["subcommand"],
                    "execution_time_ms": r["execution_time_ms"],
                    "success":           r["success"],
                    "error_code":        r["error_code"],
                }
                for r in newest
            ],
            "all_commands": [
                {
                    "command":    r["command_name"],
                    "subcommand": r["subcommand"] or None,
                    "uses":       r["uses"],
                    "unique_users": r["unique_users"],
                }
                for r in all_cmds
            ],
            "totals": {
                "total_executions":     int(totals["total_executions"] or 0),
                "executions_today":     int(totals["executions_today"] or 0),
                "executions_24h":       int(totals["executions_24h"] or 0),
                "unique_users":         int(totals["unique_users"] or 0),
                "avg_execution_time_ms": float(totals["avg_execution_time_ms"] or 0),
                "overall_success_rate": float(totals["overall_success_rate"] or 100),
            },
            "range": range_,
        }
