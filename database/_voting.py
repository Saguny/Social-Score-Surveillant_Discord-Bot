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
