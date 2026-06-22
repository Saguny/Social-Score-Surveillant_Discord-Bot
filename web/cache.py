import asyncio
import logging
import time

from web.anonymize import pseudonym_user, redact_global_stats

logger = logging.getLogger(__name__)


_REASON_MAX_LEN = 40


def _safe_reason(raw) -> str | None:
    if not raw:
        return None
    category = str(raw).split(":", 1)[0].strip()
    if not category:
        return None
    return category[:_REASON_MAX_LEN]


def format_event(row) -> dict:
    return {
        "user": pseudonym_user(row["user_id"]),
        "delta": round(float(row["delta"]), 2),
        "timestamp": int(row["timestamp"]),
        "reason": _safe_reason(row["reason"]),
    }


class StatCache:
    STATS_INTERVAL = 60
    TIMELINE_INTERVAL = 300
    VOTES_INTERVAL = 300
    GUILD_LIST_INTERVAL = 600
    LATENCY_INTERVAL = 5
    FEED_INTERVAL = 5

    TIMELINE_RANGES = ("24h", "7d", "30d", "90d")
    VOTE_PERIODS = ("1D", "7D", "1M", "TOTAL")

    def __init__(self, bot, hub=None):
        self.bot = bot
        self.hub = hub
        self._data: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []
        self._last_feed_ts = 0

    def get(self, key: str):
        return self._data.get(key)

    async def start(self):
        await asyncio.gather(
            self._safe(self._refresh_stats),
            self._safe(self._refresh_timeline),
            self._safe(self._refresh_votes),
            self._safe(self._refresh_guild_list),
            self._safe(self._refresh_latency),
            self._safe(self._refresh_feed),
        )
        self._tasks = [
            asyncio.create_task(self._loop(self._refresh_stats, self.STATS_INTERVAL)),
            asyncio.create_task(self._loop(self._refresh_timeline, self.TIMELINE_INTERVAL)),
            asyncio.create_task(self._loop(self._refresh_votes, self.VOTES_INTERVAL)),
            asyncio.create_task(self._loop(self._refresh_guild_list, self.GUILD_LIST_INTERVAL)),
            asyncio.create_task(self._loop(self._refresh_latency, self.LATENCY_INTERVAL)),
            asyncio.create_task(self._loop(self._refresh_feed, self.FEED_INTERVAL)),
        ]

    async def stop(self):
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.exception("StatCache task raised on shutdown")
        self._tasks = []

    async def _loop(self, fn, interval):
        while True:
            await asyncio.sleep(interval)
            await self._safe(fn)

    async def _safe(self, fn):
        try:
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("StatCache refresh failed: %s", getattr(fn, "__name__", fn))

    async def _refresh_stats(self):
        stats = await self.bot.db.get_global_stats()
        redact_global_stats(stats)
        self.augment_live_fields(stats)
        self._data["stats"] = stats
        if self.hub:
            await self.hub.publish("stats", stats)

    def augment_live_fields(self, stats):
        latency = self._data.get("latency") or {}
        stats["db_query_ms"] = latency.get("db_query_ms")
        stats["discord_ping_ms"] = latency.get("discord_ping_ms")
        stats["uptime_seconds"] = int(time.time() - self.bot.start_time.timestamp()) if getattr(self.bot, "start_time", None) else 0
        stats["total_guilds"] = len(self.bot.guilds)
        scoring_cog = self.bot.get_cog("Scoring")
        executor = getattr(scoring_cog, "_executor", None)
        max_workers = getattr(executor, "_max_workers", None) if executor else None
        active_workers = len(getattr(executor, "_processes", None) or {}) if executor else None
        stats["sentiment_workers_max"] = max_workers if isinstance(max_workers, int) else None
        stats["sentiment_workers_active"] = active_workers if isinstance(active_workers, int) else None

    async def _refresh_timeline(self):
        results = await asyncio.gather(*(self.bot.db.get_global_timeline(rng) for rng in self.TIMELINE_RANGES))
        for rng, data in zip(self.TIMELINE_RANGES, results):
            self._data[f"timeline:{rng}"] = data

    async def _refresh_votes(self):
        results = await asyncio.gather(*(self.bot.db.get_topgg_vote_timeline(period) for period in self.VOTE_PERIODS))
        for period, buckets in zip(self.VOTE_PERIODS, results):
            total = sum(row["votes"] for row in buckets)
            self._data[f"votes:{period}"] = {"period": period, "buckets": buckets, "total": total}

    async def _refresh_guild_list(self):
        guilds = sorted(self.bot.guilds, key=lambda g: g.name.lower())
        self._data["guilds"] = {
            "guilds": [
                {"id": str(g.id), "name": g.name, "member_count": g.member_count or 0}
                for g in guilds
            ]
        }

    async def _refresh_latency(self):
        t0 = time.time()
        await self.bot.db.ping()
        payload = {
            "db_query_ms": round((time.time() - t0) * 1000, 1),
            "discord_ping_ms": round(self.bot.latency * 1000, 1) if self.bot.latency else None,
        }
        self._data["latency"] = payload
        if self.hub:
            await self.hub.publish("latency", payload)

    async def _refresh_feed(self):
        rows = await self.bot.db.get_recent_events(20)
        events = [format_event(r) for r in rows]
        self._data["feed"] = {"events": events}
        if not rows:
            return
        new_rows = [r for r in rows if int(r["timestamp"]) > self._last_feed_ts]
        self._last_feed_ts = int(rows[0]["timestamp"])
        if self.hub and new_rows:
            for row in reversed(new_rows):
                await self.hub.publish("feed", format_event(row))
