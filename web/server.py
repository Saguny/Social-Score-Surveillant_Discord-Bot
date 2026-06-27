import os
import hmac
import time
import json
import hashlib
import secrets
import asyncio
from pathlib import Path
from aiohttp import web

from web.cache import StatCache, format_event
from web.sse import SSEHub
from web.anonymize import redact_global_stats, pseudonym_user, pseudonym_guild, using_fallback_salt
from infra.redis_cache import cache_get, cache_set, cache_delete
from infra.admin_rpc import call_admin_rpc, fire_admin_rpc

PORT = int(os.getenv("PORT", 8080))
_runner = None
_cache: StatCache | None = None

LEADERBOARD_LIMIT = 25

_SESSION_TTL = 60 * 60 * 24 * 30

_RATE_WINDOW  = 60 * 5
_RATE_LIMIT   = 5
_failed_attempts: dict[str, list[float]] = {}

_PUBLIC_RATE_WINDOW = 60
_PUBLIC_RATE_LIMIT  = 120
_public_hits: dict[str, list[float]] = {}

_TEMPLATE_DIR = Path(__file__).parent / 'templates'


def _load_template(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding='utf-8')


async def _is_authed(request) -> bool:
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        return True
    cookie = request.cookies.get("auth", "")
    if not cookie:
        return False
    return bool(await cache_get(f"websession:{cookie}"))


def _client_ip(request) -> str:
    xff = request.headers.get("X-Forwarded-For", "")
    if xff:
        hops = [h.strip() for h in xff.split(",") if h.strip()]
        if hops:
            return hops[-1]
    return request.remote or ""


def _admin_ip_allowed(request) -> bool:
    allowlist = [ip.strip() for ip in os.getenv("ADMIN_ALLOWED_IPS", "").split(",") if ip.strip()]
    if not allowlist:
        return True
    return _client_ip(request) in allowlist


def _require_admin_ip(handler):
    async def middleware(request):
        if not _admin_ip_allowed(request):
            raise web.HTTPForbidden(text="Access denied.")
        return await handler(request)
    return middleware


def _require_admin(handler):
    async def middleware(request):
        if not _admin_ip_allowed(request):
            raise web.HTTPForbidden(text="Access denied.")
        if not await _is_authed(request):
            next_url = str(request.rel_url)
            raise web.HTTPFound(f"/login?next={next_url}")
        return await handler(request)
    return middleware


def _is_public_rate_limited(request) -> bool:
    ip = _client_ip(request)
    now = time.time()
    hits = [t for t in _public_hits.get(ip, []) if now - t < _PUBLIC_RATE_WINDOW]
    if len(hits) >= _PUBLIC_RATE_LIMIT:
        _public_hits[ip] = hits
        return True
    hits.append(now)
    _public_hits[ip] = hits
    return False


def _rate_limit_public(handler):
    async def middleware(request):
        if _is_public_rate_limited(request):
            return web.json_response({"error": "Too many requests."}, status=429)
        return await handler(request)
    return middleware


async def _handle_login(request):
    return web.Response(text=_load_template('login.html'), content_type='text/html')


async def _handle_auth(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    ip = _client_ip(request)

    now = time.time()
    attempts = _failed_attempts.get(ip, [])
    attempts = [t for t in attempts if now - t < _RATE_WINDOW]
    if len(attempts) >= _RATE_LIMIT:
        return web.Response(status=429)

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    provided = body.get("token", "")
    if not admin_token or not hmac.compare_digest(provided, admin_token):
        attempts.append(now)
        _failed_attempts[ip] = attempts
        return web.Response(status=403)

    _failed_attempts.pop(ip, None)
    session_token = secrets.token_hex(32)
    await cache_set(f"websession:{session_token}", "1", ex=_SESSION_TTL)
    response = web.Response(status=200)
    response.set_cookie("auth", session_token, httponly=True, secure=True, samesite="Strict", max_age=_SESSION_TTL)
    return response


async def _handle_index(request):
    return web.Response(text=_load_template('index.html'), content_type='text/html')


async def _handle_admin(request):
    return web.Response(text=_load_template('admin.html'), content_type='text/html')


async def _handle_privacy(request):
    return web.Response(text=_load_template('privacy.html'), content_type='text/html')


async def _handle_terms(request):
    return web.Response(text=_load_template('terms.html'), content_type='text/html')


async def _handle_leaderboards_page(request):
    return web.Response(text=_load_template('leaderboards.html'), content_type='text/html')


_BOT_COMMANDS = {"sync", "guilds", "reload", "restart", "shutdown"}


async def _handle_admin_command(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    command = body.get("command", "")
    args = body.get("args", [])
    db = request.app["db"]

    if command in _BOT_COMMANDS:
        rpc_payload = {"cog": args[0]} if command == "reload" and args else {}
        result = await call_admin_rpc(command, rpc_payload)
        return web.json_response(result)

    elif command == "force_reset":
        if len(args) < 2:
            return web.json_response({"error": "Usage: force_reset <guild_id> <user_id>"})
        try:
            gid, uid = int(args[0]), int(args[1])
            user = await db.get_user(gid, uid)
            delta = 750.0 - user["score"]
            await db.update_score(gid, uid, delta, "admin force reset")
            return web.json_response({"output": f"User {uid} in guild {gid} reset to 750."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "force_yuan":
        if len(args) < 3:
            return web.json_response({"error": "Usage: force_yuan <guild_id> <user_id> <amount>"})
        try:
            gid, uid, amount = int(args[0]), int(args[1]), int(args[2])
            await db.set_yuan(gid, uid, amount)
            return web.json_response({"output": f"User {uid} in guild {gid} yuan set to {amount}."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "force_score":
        if len(args) < 3:
            return web.json_response({"error": "Usage: force_score <guild_id> <user_id> <score>"})
        try:
            gid, uid, score = int(args[0]), int(args[1]), float(args[2])
            await db.set_score(gid, uid, score)
            return web.json_response({"output": f"User {uid} in guild {gid} score set to {score}."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "db_reset":
        if not args:
            return web.json_response({"error": "Usage: db_reset <guild_id>"})
        try:
            gid = int(args[0])
            await db.reset_guild_db(gid)
            return web.json_response({"output": f"Guild {gid} wiped."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    return web.json_response({"error": f"Unknown command: {command}"}, status=400)


async def _handle_topgg_webhook(request):
    secret = os.getenv("TOPGG_WEBHOOK_SECRET", "")
    if not secret:
        print("[topgg webhook] rejected: TOPGG_WEBHOOK_SECRET is not set")
        return web.Response(status=403)

    raw_body = await request.text()
    signature = request.headers.get("x-topgg-signature", "")
    if not signature:
        print(f"[topgg webhook] rejected: missing x-topgg-signature header (headers={list(request.headers.keys())})")
        return web.Response(status=403)

    try:
        parts = dict(p.split("=", 1) for p in signature.split(","))
        timestamp, received_sig = parts["t"], parts["v1"]
    except (KeyError, ValueError):
        print(f"[topgg webhook] rejected: malformed x-topgg-signature header {signature!r}")
        return web.Response(status=400)

    expected_sig = hmac.new(secret.encode(), f"{timestamp}.{raw_body}".encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_sig, expected_sig):
        print("[topgg webhook] rejected: signature mismatch")
        return web.Response(status=403)

    try:
        body = json.loads(raw_body)
    except Exception as e:
        print(f"[topgg webhook] rejected: invalid JSON body ({e!r})")
        return web.Response(status=400)

    event_type = body.get("type")
    if event_type == "webhook.test":
        print(f"[topgg webhook] test received and verified, body={body}")
        return web.Response(status=200)
    if event_type != "vote.create":
        print(f"[topgg webhook] ignored: unrecognized event type={event_type!r} body={body}")
        return web.Response(status=200)

    try:
        user_id = int(body["data"]["user"]["platform_id"])
    except (KeyError, TypeError, ValueError):
        print(f"[topgg webhook] rejected: could not extract user platform_id from body={body}")
        return web.Response(status=400)

    print(f"[topgg webhook] vote.create received from user {user_id}, dispatching process_vote")
    await fire_admin_rpc("process_vote", {"user_id": user_id})
    return web.Response(status=200)


async def _handle_stats(request):
    db = request.app["db"]
    cache = request.app.get("cache")

    if cache:
        stats = dict(cache.get("stats") or {})
        if not stats:
            stats = await db.get_global_stats()
            redact_global_stats(stats)
        cache.augment_live_fields(stats)
        if stats.get("db_query_ms") is None:
            t0 = time.time()
            await db.ping()
            stats["db_query_ms"] = round((time.time() - t0) * 1000, 1)
    else:
        t0 = time.time()
        stats = await db.get_global_stats()
        redact_global_stats(stats)
        stats["db_query_ms"] = round((time.time() - t0) * 1000, 1)
        bot_status = await call_admin_rpc("get_status")
        stats["uptime_seconds"] = bot_status.get("uptime_seconds", 0)
        stats["discord_ping_ms"] = bot_status.get("discord_ping_ms")
        stats["total_guilds"] = bot_status.get("total_guilds", 0)
        stats["sentiment_workers_max"] = bot_status.get("sentiment_workers_max")
        stats["sentiment_workers_active"] = bot_status.get("sentiment_workers_active")

    return web.json_response(stats)


async def _handle_stats_timeline(request):
    db = request.app["db"]
    range_ = request.query.get("range", "30d")
    if range_ not in ("24h", "7d", "30d", "90d"):
        range_ = "30d"

    cache = request.app.get("cache")
    if cache:
        cached = cache.get(f"timeline:{range_}")
        if cached:
            return web.json_response(cached)

    timeline = await db.get_global_timeline(range_)
    return web.json_response(timeline)


async def _handle_leaderboard(request):
    db = request.app["db"]
    earned_7d, earned_30d, earned_alltime, score_data, citizens = await asyncio.gather(
        db.get_global_yuan_earned_leaderboard(7, LEADERBOARD_LIMIT),
        db.get_global_yuan_earned_leaderboard(30, LEADERBOARD_LIMIT),
        db.get_global_yuan_earned_leaderboard(None, LEADERBOARD_LIMIT),
        db.get_global_leaderboard(LEADERBOARD_LIMIT),
        db.get_global_citizens_leaderboard(LEADERBOARD_LIMIT),
    )
    all_uids = list({
        r["user_id"]
        for rows in (earned_7d, earned_30d, earned_alltime, score_data["by_yuan"], score_data["by_score"], citizens)
        for r in rows
    })
    display_names = await db.get_leaderboard_display_names(all_uids)

    def _name(uid):
        return display_names.get(uid) or pseudonym_user(uid)

    return web.json_response({
        "generated_at": int(time.time()),
        "top_balance": [
            {"user": _name(r["user_id"]), "yuan": int(r["total_yuan"])}
            for r in score_data["by_yuan"]
        ],
        "top_earned": {
            "7d":      [{"user": _name(r["user_id"]), "earned": r["earned"]} for r in earned_7d],
            "30d":     [{"user": _name(r["user_id"]), "earned": r["earned"]} for r in earned_30d],
            "alltime": [{"user": _name(r["user_id"]), "earned": r["earned"]} for r in earned_alltime],
        },
        "top_score": [
            {"user": _name(r["user_id"]), "score": round(float(r["avg_score"]), 2)}
            for r in score_data["by_score"]
        ],
        "top_citizens": [
            {"user": _name(r["user_id"]), "score": round(float(r["avg_score"]), 2), "yuan": int(r["total_yuan"])}
            for r in citizens
        ],
    })


_VALID_GUILD_METRICS  = {"happiness", "gdp", "civic", "literacy", "incarceration", "politburo"}
_VALID_GUILD_BRACKETS = {"Outpost", "Town", "Metropolis"}

async def _handle_guild_leaderboard(request):
    db = request.app["db"]
    metric  = request.rel_url.query.get("metric", "happiness")
    bracket = request.rel_url.query.get("bracket", "")
    if metric not in _VALID_GUILD_METRICS:
        metric = "happiness"
    bracket_arg = bracket if bracket in _VALID_GUILD_BRACKETS else None
    try:
        limit = min(100, max(1, int(request.rel_url.query.get("limit", 25))))
    except (ValueError, TypeError):
        limit = 25
    rows, visible_ids = await asyncio.gather(
        db.get_guild_leaderboard(metric, bracket_arg, limit=limit),
        db.get_visible_guild_ids(),
    )
    return web.json_response([
        {
            "guild_name": r["guild_name"] if (r.get("guild_id") in visible_ids and r.get("guild_name")) else pseudonym_guild(r["guild_id"]),
            "citizens":   int(r.get("citizens") or 0),
            "value":      round(float(r["value"]), 4) if r.get("value") is not None else None,
        }
        for r in rows
    ])


async def _handle_recent_events(request):
    db = request.app["db"]
    cache = request.app.get("cache")
    if cache:
        cached = cache.get("feed")
        if cached:
            return web.json_response(cached)

    rows = await db.get_recent_events(20)
    events = [format_event(r) for r in rows]
    return web.json_response({"events": events})


_CMD_STATS_CACHE_TTL = 60  # seconds


async def _handle_stats_commands(request):
    db = request.app["db"]
    range_ = request.query.get("range", "7d")
    if range_ not in ("24h", "7d", "30d", "all"):
        range_ = "7d"

    cache_key = f"cmd_stats_v2:{range_}"
    cached = await cache_get(cache_key)
    if cached:
        try:
            return web.json_response(json.loads(cached))
        except Exception:
            pass

    data = await db.get_command_stats(range_)
    # Replace raw user_id with a pseudonym before it leaves the server
    for row in data.get("newest_commands", []):
        row["user"] = pseudonym_user(row.pop("user_id", 0))
    await cache_set(cache_key, json.dumps(data), ex=_CMD_STATS_CACHE_TTL)
    return web.json_response(data)


async def _handle_stats_all(request):
    db = request.app["db"]
    cache = request.app.get("cache")
    range_ = request.query.get("range", "30d")
    if range_ not in ("24h", "7d", "30d", "90d"):
        range_ = "30d"

    async def _get_stats():
        if cache:
            s = dict(cache.get("stats") or {})
            if not s:
                s = await db.get_global_stats()
                redact_global_stats(s)
            cache.augment_live_fields(s)
            if s.get("db_query_ms") is None:
                t0 = time.time()
                await db.ping()
                s["db_query_ms"] = round((time.time() - t0) * 1000, 1)
        else:
            t0 = time.time()
            s = await db.get_global_stats()
            redact_global_stats(s)
            s["db_query_ms"] = round((time.time() - t0) * 1000, 1)
            bot_status = await call_admin_rpc("get_status")
            s["uptime_seconds"] = bot_status.get("uptime_seconds", 0)
            s["discord_ping_ms"] = bot_status.get("discord_ping_ms")
            s["total_guilds"] = bot_status.get("total_guilds", 0)
            s["sentiment_workers_max"] = bot_status.get("sentiment_workers_max")
            s["sentiment_workers_active"] = bot_status.get("sentiment_workers_active")
        return s

    async def _get_timeline():
        if cache:
            cached = cache.get(f"timeline:{range_}")
            if cached:
                return cached
        return await db.get_global_timeline(range_)

    async def _get_events():
        if cache:
            cached = cache.get("feed")
            if cached:
                return cached
        rows = await db.get_recent_events(20)
        return {"events": [format_event(r) for r in rows]}

    async def _get_announcement():
        return await db.get_dashboard_announcement()

    stats, timeline, events, announcement = await asyncio.gather(
        _get_stats(), _get_timeline(), _get_events(), _get_announcement()
    )
    return web.json_response({
        "stats": stats,
        "timeline": timeline,
        "events": events,
        "announcement": announcement,
        "range": range_,
    })


async def _handle_topgg_votes(request):
    db = request.app["db"]
    period = request.query.get("period", "7D").upper()
    if period not in ("1D", "7D", "1M", "TOTAL"):
        period = "7D"

    cache = request.app.get("cache")
    if cache:
        cached = cache.get(f"votes:{period}")
        if cached:
            return web.json_response(cached)

    buckets = await db.get_topgg_vote_timeline(period)
    total = sum(row["votes"] for row in buckets)
    return web.json_response({"period": period, "buckets": buckets, "total": total})


async def _handle_sse(request):
    hub = request.app["sse_hub"]
    return await hub.stream(request)


async def _handle_robots(request):
    return web.Response(text="User-agent: *\nDisallow: /\n", content_type="text/plain")


async def _handle_guild_list(request):
    cache = request.app.get("cache")
    if cache:
        cached = cache.get("guilds")
        if cached:
            return web.json_response(cached)

    result = await call_admin_rpc("get_guild_list")
    return web.json_response(result)


async def _handle_user_lookup(request):
    user_id_raw = request.query.get("user_id", "").strip()
    try:
        int(user_id_raw)
    except ValueError:
        return web.json_response({"error": "Invalid user ID."}, status=400)

    result = await call_admin_rpc("user_lookup", {"user_id": user_id_raw})
    status = 400 if "error" in result else 200
    if "error" in result and "No Discord user found" in result["error"]:
        status = 404
    return web.json_response(result, status=status)


async def _handle_user_yuan_adjust(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    result = await call_admin_rpc("user_yuan_adjust", body)
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status)


async def _handle_broadcast_embed(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    result = await call_admin_rpc("broadcast_embed", body, timeout=30.0)
    status = 400 if "error" in result else 200
    return web.json_response(result, status=status)


async def _handle_announcement(request):
    db = request.app["db"]
    announcement = await db.get_dashboard_announcement()
    return web.json_response(announcement)


async def _handle_admin_announcement_set(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    enabled = bool(body.get("enabled"))
    message = str(body.get("message") or "")[:500]
    severity = body.get("severity") or "info"
    if severity not in ("info", "warn", "danger"):
        severity = "info"

    db = request.app["db"]
    await db.set_dashboard_announcement(enabled, message, severity)
    announcement = await db.get_dashboard_announcement()
    return web.json_response(announcement)


async def start_web_server(db):
    global _runner, _cache
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        return

    hub = SSEHub()
    cache = StatCache(db, hub)
    await cache.start()
    _cache = cache

    app = web.Application()
    app["db"] = db
    app["cache"] = cache
    app["sse_hub"] = hub
    app.router.add_get("/login", _require_admin_ip(_handle_login))
    app.router.add_post("/api/auth", _require_admin_ip(_handle_auth))
    app.router.add_get("/", _rate_limit_public(_handle_index))
    app.router.add_get("/privacy", _rate_limit_public(_handle_privacy))
    app.router.add_get("/terms", _rate_limit_public(_handle_terms))
    app.router.add_get("/leaderboards", _rate_limit_public(_handle_leaderboards_page))
    app.router.add_get("/admin", _require_admin(_handle_admin))
    app.router.add_post("/api/admin/command", _require_admin(_handle_admin_command))
    app.router.add_get("/api/stats", _rate_limit_public(_handle_stats))
    app.router.add_get("/api/stats/commands", _rate_limit_public(_handle_stats_commands))
    app.router.add_get("/api/stats/all", _rate_limit_public(_handle_stats_all))
    app.router.add_get("/api/stats/timeline", _rate_limit_public(_handle_stats_timeline))
    app.router.add_get("/api/stats/recent-events", _rate_limit_public(_handle_recent_events))
    app.router.add_get("/api/leaderboard", _rate_limit_public(_handle_leaderboard))
    app.router.add_get("/api/leaderboards/guilds", _rate_limit_public(_handle_guild_leaderboard))
    app.router.add_get("/api/stream", _rate_limit_public(_handle_sse))
    app.router.add_get("/api/admin/topgg-votes", _require_admin(_handle_topgg_votes))
    app.router.add_get("/api/admin/guild-list", _require_admin(_handle_guild_list))
    app.router.add_get("/api/admin/user-lookup", _require_admin(_handle_user_lookup))
    app.router.add_post("/api/admin/user-yuan-adjust", _require_admin(_handle_user_yuan_adjust))
    app.router.add_post("/api/admin/broadcast-embed", _require_admin(_handle_broadcast_embed))
    app.router.add_get("/api/announcement", _rate_limit_public(_handle_announcement))
    app.router.add_post("/api/admin/announcement", _require_admin(_handle_admin_announcement_set))
    app.router.add_post("/webhooks/topgg", _handle_topgg_webhook)
    app.router.add_get("/robots.txt", _handle_robots)
    app.router.add_static('/static', Path(__file__).parent / 'static', name='static')

    if using_fallback_salt():
        print("[web] WARNING: PSEUDONYM_SALT is not set — public stats are using a default, predictable salt. Set PSEUDONYM_SALT to a random secret.")
    if not os.getenv("ADMIN_ALLOWED_IPS"):
        print("[web] WARNING: ADMIN_ALLOWED_IPS is not set — /admin is reachable from any IP (still token-gated).")

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")
