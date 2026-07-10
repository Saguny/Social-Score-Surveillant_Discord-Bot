import asyncio
import logging
import time

import aiohttp

from web.anonymize import pseudonym_user, redact_global_stats
from infra.admin_rpc import call_admin_rpc

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
    BOT_STATUS_INTERVAL = 15

    TIMELINE_RANGES = ("24h", "7d", "30d", "90d")
    VOTE_PERIODS = ("1D", "7D", "1M", "TOTAL")

    def __init__(self, db, hub=None):
        self.db = db
        self.hub = hub
        self._data: dict[str, dict] = {}
        self._tasks: list[asyncio.Task] = []
        self._last_feed_ts = 0
        self._http: aiohttp.ClientSession | None = None

    def get(self, key: str):
        return self._data.get(key)

    async def start(self):
        self._http = aiohttp.ClientSession()
        await asyncio.gather(
            self._safe(self._refresh_bot_status),
            self._safe(self._refresh_stats),
            self._safe(self._refresh_timeline),
            self._safe(self._refresh_votes),
            self._safe(self._refresh_guild_list),
            self._safe(self._refresh_latency),
            self._safe(self._refresh_feed),
        )
        self._tasks = [
            asyncio.create_task(self._loop(self._refresh_bot_status, self.BOT_STATUS_INTERVAL)),
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
        if self._http:
            await self._http.close()
            self._http = None

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

    async def _refresh_bot_status(self):
        status = await call_admin_rpc("get_status")
        if "error" not in status:
            self._data["bot_status"] = status

    async def _refresh_stats(self):
        stats = await self.db.get_global_stats()
        redact_global_stats(stats)
        self.augment_live_fields(stats)
        self._data["stats"] = stats
        if self.hub:
            await self.hub.publish("stats", stats)

    def augment_live_fields(self, stats):
        latency = self._data.get("latency") or {}
        bot_status = self._data.get("bot_status") or {}
        stats["db_query_ms"] = latency.get("db_query_ms")
        stats["discord_ping_ms"] = bot_status.get("discord_ping_ms")
        stats["discord_rest_ms"] = latency.get("discord_rest_ms")
        stats["uptime_seconds"] = bot_status.get("uptime_seconds", 0)
        stats["total_guilds"] = bot_status.get("total_guilds", 0)
        stats["sentiment_workers_max"] = bot_status.get("sentiment_workers_max")
        stats["sentiment_workers_active"] = bot_status.get("sentiment_workers_active")

    async def _refresh_timeline(self):
        results = await asyncio.gather(*(self.db.get_global_timeline(rng) for rng in self.TIMELINE_RANGES))
        for rng, data in zip(self.TIMELINE_RANGES, results):
            self._data[f"timeline:{rng}"] = data

    async def _refresh_votes(self):
        results = await asyncio.gather(*(self.db.get_topgg_vote_timeline(period) for period in self.VOTE_PERIODS))
        for period, buckets in zip(self.VOTE_PERIODS, results):
            total = sum(row["votes"] for row in buckets)
            self._data[f"votes:{period}"] = {"period": period, "buckets": buckets, "total": total}

    async def _refresh_guild_list(self):
        result = await call_admin_rpc("get_guild_list")
        if "error" not in result:
            self._data["guilds"] = result

    async def _refresh_latency(self):
        t0 = time.time()
        await self.db.ping()
        db_ms = round((time.time() - t0) * 1000, 1)

        discord_rest_ms = None
        if self._http:
            try:
                t1 = time.time()
                async with self._http.get(
                    "https://discord.com/api/v10/gateway",
                    timeout=aiohttp.ClientTimeout(total=5),
                ) as resp:
                    await resp.read()
                discord_rest_ms = round((time.time() - t1) * 1000, 1)
            except Exception:
                pass

        payload = {
            "db_query_ms": db_ms,
            "discord_rest_ms": discord_rest_ms,
        }
        self._data["latency"] = payload
        if self.hub:
            await self.hub.publish("latency", {
                **payload,
                "discord_ping_ms": (self._data.get("bot_status") or {}).get("discord_ping_ms"),
            })

    async def _refresh_feed(self):
        rows = await self.db.get_recent_events(20)
        events = [format_event(r) for r in rows]
        self._data["feed"] = {"events": events}
        if not rows:
            return
        new_rows = [r for r in rows if int(r["timestamp"]) > self._last_feed_ts]
        self._last_feed_ts = int(rows[0]["timestamp"])
        if self.hub and new_rows:
            for row in reversed(new_rows):
                await self.hub.publish("feed", format_event(row))
