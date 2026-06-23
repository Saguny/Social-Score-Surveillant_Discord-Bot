import time


class VotingMixin:
    async def set_vote_reminder(self, user_id: int, remind_at: int):
        await self._pool.execute(
            "INSERT INTO vote_reminders (user_id, remind_at) VALUES ($1, $2) ON CONFLICT (user_id) DO UPDATE SET remind_at = $2",
            user_id, remind_at,
        )

    async def get_due_vote_reminders(self) -> list[int]:
        rows = await self._pool.fetch(
            "DELETE FROM vote_reminders WHERE remind_at <= $1 RETURNING user_id",
            int(time.time()),
        )
        return [row["user_id"] for row in rows]

    async def log_topgg_vote(self, user_id: int):
        await self._pool.execute(
            "INSERT INTO topgg_votes (user_id, voted_at) VALUES ($1, $2)",
            user_id, int(time.time()),
        )

    async def get_topgg_vote_timeline(self, period: str) -> list[dict]:
        now = int(time.time())
        period = period.upper()
        if period == "1D":
            since, bucket_secs = now - 86400, 3600
        elif period == "7D":
            since, bucket_secs = now - 7 * 86400, 86400
        elif period == "1M":
            since, bucket_secs = now - 30 * 86400, 86400
        else:
            since, bucket_secs = 0, 86400
        rows = await self._pool.fetch(
            """
            SELECT FLOOR(voted_at::float / $1)::bigint * $1 AS bucket, COUNT(*) AS votes
            FROM topgg_votes
            WHERE voted_at >= $2
            GROUP BY bucket
            ORDER BY bucket
            """,
            bucket_secs, since,
        )
        return [{"bucket": row["bucket"], "votes": row["votes"]} for row in rows]

    async def get_top_voters_by_total(self, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            SELECT user_id, COUNT(*) AS value
            FROM topgg_votes
            GROUP BY user_id
            ORDER BY value DESC
            LIMIT $1
            """,
            limit,
        )
        return [{"user_id": row["user_id"], "value": row["value"]} for row in rows]

    async def get_top_voters_by_streak(self, limit: int = 50) -> list[dict]:
        rows = await self._pool.fetch(
            """
            WITH days AS (
                SELECT DISTINCT user_id, (voted_at / 86400) AS day FROM topgg_votes
            ), grp AS (
                SELECT user_id, day, day - ROW_NUMBER() OVER (PARTITION BY user_id ORDER BY day) AS grp
                FROM days
            ), runs AS (
                SELECT user_id, grp, COUNT(*) AS run_len FROM grp GROUP BY user_id, grp
            )
            SELECT user_id, MAX(run_len) AS value
            FROM runs
            GROUP BY user_id
            ORDER BY value DESC
            LIMIT $1
            """,
            limit,
        )
        return [{"user_id": row["user_id"], "value": row["value"]} for row in rows]
