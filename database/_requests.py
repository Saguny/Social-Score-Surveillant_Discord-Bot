import time
import asyncpg


class GachaRequestsMixin:

    async def create_request(
        self,
        discord_id: int,
        discord_username: str,
        wiki_slug: str,
        wiki_title: str,
    ) -> int:
        try:
            row = await self._pool.fetchrow(
                """
                INSERT INTO gacha_requests (discord_id, discord_username, wiki_slug, wiki_title, submitted_at)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                discord_id, discord_username, wiki_slug, wiki_title, int(time.time()),
            )
        except asyncpg.UniqueViolationError:
            raise ValueError("already_requested")
        return row["id"]

    async def get_request_by_slug(self, wiki_slug: str) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gacha_requests WHERE wiki_slug = $1 AND status != 'approved'",
                wiki_slug,
            )
        return dict(row) if row else None

    async def add_vote(self, request_id: int, discord_id: int, discord_username: str) -> bool:
        row = await self._pool.fetchrow(
            """
            INSERT INTO gacha_request_votes (request_id, discord_id, discord_username, voted_at)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (request_id, discord_id) DO NOTHING
            RETURNING 1
            """,
            request_id, discord_id, discord_username, int(time.time()),
        )
        return row is not None

    async def remove_vote(self, request_id: int, discord_id: int) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM gacha_request_votes WHERE request_id=$1 AND discord_id=$2 RETURNING 1",
            request_id, discord_id,
        )
        return row is not None

    async def get_vote_count(self, request_id: int) -> int:
        row = await self._pool.fetchrow(
            "SELECT COUNT(*) AS n FROM gacha_request_votes WHERE request_id=$1",
            request_id,
        )
        return row["n"] if row else 0

    async def get_recent_voters(self, request_id: int, limit: int = 4) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT discord_id, discord_username FROM gacha_request_votes "
                "WHERE request_id=$1 ORDER BY voted_at ASC LIMIT $2",
                request_id, limit,
            )
        return [dict(r) for r in rows]

    async def has_voted(self, request_id: int, discord_id: int) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM gacha_request_votes WHERE request_id=$1 AND discord_id=$2",
            request_id, discord_id,
        )
        return row is not None

    async def get_pending_requests(self, limit: int = 50, sort: str = "votes") -> list[dict]:
        order = "r.submitted_at DESC" if sort == "newest" else "vote_count DESC, r.submitted_at ASC"
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT r.*,
                       COUNT(v.discord_id) AS vote_count
                FROM gacha_requests r
                LEFT JOIN gacha_request_votes v ON v.request_id = r.id
                WHERE r.status = 'pending'
                GROUP BY r.id
                ORDER BY {order}
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def get_top_requests(self, limit: int = 5) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id, r.wiki_slug, r.wiki_title, r.discord_username, r.submitted_at,
                       COUNT(v.discord_id) AS vote_count
                FROM gacha_requests r
                LEFT JOIN gacha_request_votes v ON v.request_id = r.id
                WHERE r.status = 'pending'
                GROUP BY r.id
                ORDER BY vote_count DESC, r.submitted_at ASC
                LIMIT $1
                """,
                limit,
            )
        return [dict(r) for r in rows]

    async def set_request_status(
        self,
        request_id: int,
        status: str,
        rejection_reason: str | None = None,
    ) -> None:
        await self._pool.execute(
            """
            UPDATE gacha_requests
            SET status = $2, reviewed_at = $3, rejection_reason = $4
            WHERE id = $1
            """,
            request_id, status, int(time.time()), rejection_reason,
        )

    async def set_request_approved_atomic(self, request_id: int) -> bool:
        """Atomically transition status pending → approved. Returns True only on first approval."""
        row = await self._pool.fetchrow(
            "UPDATE gacha_requests SET status = 'approved', reviewed_at = $2 WHERE id = $1 AND status = 'pending' RETURNING 1",
            request_id, int(time.time()),
        )
        return row is not None

    async def get_voters_for_requests(self, request_ids: list[int], voter_limit: int = 4) -> dict[int, list[dict]]:
        """Batch fetch recent voters for multiple requests. Returns dict keyed by request_id."""
        if not request_ids:
            return {}
        rows = await self._pool.fetch(
            """
            SELECT DISTINCT ON (request_id, discord_id) request_id, discord_id, discord_username
            FROM gacha_request_votes
            WHERE request_id = ANY($1)
            ORDER BY request_id, discord_id, voted_at ASC
            """,
            request_ids,
        )
        result: dict[int, list[dict]] = {rid: [] for rid in request_ids}
        counts: dict[int, int] = {}
        for r in rows:
            rid = r["request_id"]
            if counts.get(rid, 0) < voter_limit:
                result[rid].append({"discord_id": r["discord_id"], "discord_username": r["discord_username"]})
                counts[rid] = counts.get(rid, 0) + 1
        return result

    async def get_user_votes_for_requests(self, discord_id: int, request_ids: list[int]) -> set[int]:
        """Returns the set of request_ids that this user has voted on."""
        if not request_ids or not discord_id:
            return set()
        rows = await self._pool.fetch(
            "SELECT request_id FROM gacha_request_votes WHERE discord_id = $1 AND request_id = ANY($2)",
            discord_id, request_ids,
        )
        return {r["request_id"] for r in rows}

    async def get_user_request_count_today(self, discord_id: int) -> int:
        now = int(time.time())
        day_start = now - (now % 86400)
        row = await self._pool.fetchrow(
            "SELECT COUNT(*) AS n FROM gacha_requests WHERE discord_id=$1 AND submitted_at >= $2",
            discord_id, day_start,
        )
        return row["n"] if row else 0

    async def ban_submitter(self, discord_id: int) -> None:
        await self._pool.execute(
            """
            INSERT INTO gacha_request_bans (discord_id, banned_at)
            VALUES ($1, $2)
            ON CONFLICT (discord_id) DO NOTHING
            """,
            discord_id, int(time.time()),
        )

    async def is_submitter_banned(self, discord_id: int) -> bool:
        row = await self._pool.fetchrow(
            "SELECT 1 FROM gacha_request_bans WHERE discord_id=$1",
            discord_id,
        )
        return row is not None

    async def get_request_voters_for_dm(self, request_id: int) -> list[int]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT DISTINCT discord_id FROM gacha_request_votes WHERE request_id=$1",
                request_id,
            )
        return [r["discord_id"] for r in rows]

    async def get_user_requests(self, discord_id: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT * FROM gacha_requests WHERE discord_id = $1 ORDER BY submitted_at DESC",
                discord_id,
            )
        return [dict(r) for r in rows]

    async def get_user_requests_with_votes(self, discord_id: int) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT r.id, r.wiki_slug, r.wiki_title, r.status, r.submitted_at,
                       COUNT(v.discord_id) AS vote_count
                FROM gacha_requests r
                LEFT JOIN gacha_request_votes v ON v.request_id = r.id
                WHERE r.discord_id = $1
                GROUP BY r.id
                ORDER BY r.submitted_at DESC
                """,
                discord_id,
            )
        return [dict(r) for r in rows]

    async def delete_own_request(self, request_id: int, discord_id: int) -> bool:
        row = await self._pool.fetchrow(
            "DELETE FROM gacha_requests WHERE id = $1 AND discord_id = $2 AND status = 'pending' RETURNING id",
            request_id, discord_id,
        )
        return row is not None

    async def get_request_by_id(self, request_id: int) -> dict | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM gacha_requests WHERE id=$1",
                request_id,
            )
        return dict(row) if row else None

    async def update_request_overrides(
        self,
        request_id: int,
        rarity: str | None,
        gender: str | None,
        image_urls: list[str],
    ) -> None:
        await self._pool.execute(
            """
            UPDATE gacha_requests
            SET override_rarity = $2, override_gender = $3, override_image_urls = $4
            WHERE id = $1
            """,
            request_id, rarity, gender, image_urls,
        )
