import time


class PageViewsMixin:
    """Persistent per-page view counters.

    Postgres rather than Redis: Redis is a cache here and gets flushed, and a
    counter that silently resets to zero is worse than no counter.
    """

    async def bump_page_view(self, page: str) -> dict:
        row = await self._pool.fetchrow(
            """
            INSERT INTO page_views (page, views, since)
            VALUES ($1, 1, $2)
            ON CONFLICT (page) DO UPDATE SET views = page_views.views + 1
            RETURNING views, since
            """,
            page, int(time.time()),
        )
        return {"views": int(row["views"]), "since": int(row["since"])}

    async def get_page_views(self, page: str) -> dict:
        row = await self._pool.fetchrow(
            "SELECT views, since FROM page_views WHERE page = $1", page
        )
        if not row:
            return {"views": 0, "since": int(time.time())}
        return {"views": int(row["views"]), "since": int(row["since"])}
