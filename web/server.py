import os
import hmac
import time
import json
import hashlib
import secrets
import asyncio
import webbrowser
from pathlib import Path
from aiohttp import web
import discord

from web.cache import StatCache, format_event
from web.sse import SSEHub

PORT = int(os.getenv("PORT", 8080))
_runner = None
_cache: StatCache | None = None

_RATE_WINDOW  = 60 * 5
_RATE_LIMIT   = 5
_failed_attempts: dict[str, list[float]] = {}

_TEMPLATE_DIR = Path(__file__).parent / 'templates'


def _load_template(name: str) -> str:
    return (_TEMPLATE_DIR / name).read_text(encoding='utf-8')


def _is_authed(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        return True
    session_id = request.app.get("session_id", "")
    cookie = request.cookies.get("auth", "")
    return bool(session_id) and hmac.compare_digest(cookie, session_id)


def _require_auth(handler):
    async def middleware(request):
        if not _is_authed(request):
            next_url = str(request.rel_url)
            raise web.HTTPFound(f"/login?next={next_url}")
        return await handler(request)
    return middleware


async def _handle_login(request):
    return web.Response(text=_load_template('login.html'), content_type='text/html')


async def _handle_auth(request):
    admin_token = os.getenv("ADMIN_TOKEN", "")
    ip = request.headers.get("X-Forwarded-For", request.remote or "").split(",")[0].strip()

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
    response = web.Response(status=200)
    session_id = request.app["session_id"]
    response.set_cookie("auth", session_id, httponly=True, secure=True, samesite="Strict", max_age=60 * 60 * 24 * 30)
    return response


async def _handle_index(request):
    return web.Response(text=_load_template('index.html'), content_type='text/html')


async def _handle_admin(request):
    return web.Response(text=_load_template('admin.html'), content_type='text/html')


async def _handle_admin_command(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    command = body.get("command", "")
    args = body.get("args", [])
    bot = request.app["bot"]

    if command == "sync":
        await bot.tree.sync()
        return web.json_response({"output": "Slash commands synced."})

    elif command == "guilds":
        lines = [f"{g.id}  {g.name}  ({g.member_count} members)" for g in bot.guilds]
        return web.json_response({"output": "\n".join(lines) or "No guilds."})

    elif command == "reload":
        if not args:
            return web.json_response({"error": "Usage: reload <cog>"})
        try:
            await bot.reload_extension(args[0])
            return web.json_response({"output": f"{args[0]} reloaded."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "force_reset":
        if len(args) < 2:
            return web.json_response({"error": "Usage: force_reset <guild_id> <user_id>"})
        try:
            gid, uid = int(args[0]), int(args[1])
            user = await bot.db.get_user(gid, uid)
            delta = 750.0 - user["score"]
            await bot.db.update_score(gid, uid, delta, "admin force reset")
            return web.json_response({"output": f"User {uid} in guild {gid} reset to 750."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "force_yuan":
        if len(args) < 3:
            return web.json_response({"error": "Usage: force_yuan <guild_id> <user_id> <amount>"})
        try:
            gid, uid, amount = int(args[0]), int(args[1]), int(args[2])
            await bot.db.set_yuan(gid, uid, amount)
            return web.json_response({"output": f"User {uid} in guild {gid} yuan set to {amount}."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "db_reset":
        if not args:
            return web.json_response({"error": "Usage: db_reset <guild_id>"})
        try:
            gid = int(args[0])
            await bot.db.reset_guild_db(gid)
            return web.json_response({"output": f"Guild {gid} wiped."})
        except Exception as e:
            return web.json_response({"error": str(e)})

    elif command == "restart":
        asyncio.create_task(_delayed_restart(bot))
        return web.json_response({"output": "Restarting..."})

    elif command == "shutdown":
        asyncio.create_task(_delayed_shutdown(bot))
        return web.json_response({"output": "Shutting down..."})

    return web.json_response({"error": f"Unknown command: {command}"}, status=400)


async def _delayed_restart(bot):
    await asyncio.sleep(0.5)
    if _cache:
        await _cache.stop()
    await bot.close()
    import os as _os
    _os._exit(42)


async def _delayed_shutdown(bot):
    await asyncio.sleep(0.5)
    if _cache:
        await _cache.stop()
    await bot.close()


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
    bot = request.app["bot"]
    asyncio.create_task(_run_process_vote(bot, user_id))
    return web.Response(status=200)


async def _run_process_vote(bot, user_id):
    from cogs.voting import process_vote
    try:
        await process_vote(bot, user_id)
    except Exception as e:
        import traceback
        print(f"[topgg webhook] process_vote failed for user {user_id}: {e!r}")
        traceback.print_exc()


async def _handle_stats(request):
    bot = request.app["bot"]
    cache = request.app.get("cache")

    if cache:
        stats = dict(cache.get("stats") or {})
        if not stats:
            stats = await bot.db.get_global_stats()
        cache.augment_live_fields(stats)
        if stats.get("db_query_ms") is None:
            t0 = time.time()
            await bot.db.ping()
            stats["db_query_ms"] = round((time.time() - t0) * 1000, 1)
    else:
        t0 = time.time()
        stats = await bot.db.get_global_stats()
        stats["db_query_ms"] = round((time.time() - t0) * 1000, 1)
        stats["uptime_seconds"] = int(time.time() - bot.start_time.timestamp()) if getattr(bot, "start_time", None) else 0
        stats["discord_ping_ms"] = round(bot.latency * 1000, 1) if bot.latency else None
        scoring_cog = bot.get_cog("Scoring")
        executor = getattr(scoring_cog, "_executor", None)
        workers = getattr(executor, "_max_workers", None) if executor else None
        stats["sentiment_workers"] = workers if isinstance(workers, int) else None

    return web.json_response(stats)


async def _handle_stats_timeline(request):
    bot = request.app["bot"]
    range_ = request.query.get("range", "30d")
    if range_ not in ("24h", "7d", "30d", "90d"):
        range_ = "30d"

    cache = request.app.get("cache")
    if cache:
        cached = cache.get(f"timeline:{range_}")
        if cached:
            return web.json_response(cached)

    timeline = await bot.db.get_global_timeline(range_)
    return web.json_response(timeline)


async def _handle_recent_events(request):
    bot = request.app["bot"]
    cache = request.app.get("cache")
    if cache:
        cached = cache.get("feed")
        if cached:
            return web.json_response(cached)

    rows = await bot.db.get_recent_events(20)
    events = [format_event(bot, r) for r in rows]
    return web.json_response({"events": events})


async def _handle_topgg_votes(request):
    bot = request.app["bot"]
    period = request.query.get("period", "7D").upper()
    if period not in ("1D", "7D", "1M", "TOTAL"):
        period = "7D"

    cache = request.app.get("cache")
    if cache:
        cached = cache.get(f"votes:{period}")
        if cached:
            return web.json_response(cached)

    buckets = await bot.db.get_topgg_vote_timeline(period)
    total = sum(row["votes"] for row in buckets)
    return web.json_response({"period": period, "buckets": buckets, "total": total})


async def _handle_sse(request):
    hub = request.app["sse_hub"]
    return await hub.stream(request)


def _find_writable_channel(guild: discord.Guild) -> discord.TextChannel | None:
    candidates = []
    if guild.system_channel:
        candidates.append(guild.system_channel)
    candidates.extend(c for c in guild.text_channels if c != guild.system_channel)

    for channel in candidates:
        everyone_perms = channel.permissions_for(guild.default_role)
        bot_perms = channel.permissions_for(guild.me)
        if (
            everyone_perms.view_channel and everyone_perms.send_messages
            and bot_perms.view_channel and bot_perms.send_messages and bot_perms.embed_links
        ):
            return channel
    return None


async def _handle_guild_list(request):
    bot = request.app["bot"]
    cache = request.app.get("cache")
    if cache:
        cached = cache.get("guilds")
        if cached:
            return web.json_response(cached)

    guilds = sorted(bot.guilds, key=lambda g: g.name.lower())
    return web.json_response({
        "guilds": [
            {"id": str(g.id), "name": g.name, "member_count": g.member_count or 0}
            for g in guilds
        ]
    })


async def _handle_broadcast_embed(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    bot = request.app["bot"]
    target = str(body.get("target", "all")).strip()
    title = (body.get("title") or "").strip()
    description = (body.get("description") or "").strip()
    color_raw = (body.get("color") or "").strip().lstrip("#")
    image_url = (body.get("image_url") or "").strip()
    thumbnail_url = (body.get("thumbnail_url") or "").strip()
    fields = body.get("fields") or []
    button_label = (body.get("button_label") or "").strip()
    button_url = (body.get("button_url") or "").strip()

    if not title and not description:
        return web.json_response({"error": "Embed needs a title or description."}, status=400)

    try:
        color = int(color_raw, 16) if color_raw else 0xCC0000
    except ValueError:
        return web.json_response({"error": "Invalid color hex."}, status=400)

    view = None
    if button_label and button_url:
        if not (button_url.startswith("http://") or button_url.startswith("https://")):
            return web.json_response({"error": "Button URL must start with http:// or https://"}, status=400)
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label=button_label[:80], url=button_url, style=discord.ButtonStyle.link))

    if target == "all":
        guilds = list(bot.guilds)
    else:
        try:
            gid = int(target)
        except ValueError:
            return web.json_response({"error": "Invalid guild id."}, status=400)
        guild = bot.get_guild(gid)
        if not guild:
            return web.json_response({"error": f"Bot is not in guild {gid}."}, status=404)
        guilds = [guild]

    if not guilds:
        return web.json_response({"error": "No target guilds."}, status=400)

    results = []
    for guild in guilds:
        embed = discord.Embed(title=title or None, description=description or None, color=color)
        if image_url:
            embed.set_image(url=image_url)
        if thumbnail_url:
            embed.set_thumbnail(url=thumbnail_url)
        for f in fields[:25]:
            name = (f.get("name") or "").strip()
            value = (f.get("value") or "").strip()
            if not name or not value:
                continue
            embed.add_field(name=name, value=value, inline=bool(f.get("inline")))

        channel = _find_writable_channel(guild)
        if not channel:
            results.append({
                "guild_id": str(guild.id), "guild_name": guild.name,
                "status": "skipped", "detail": "No channel writable by @everyone found.",
            })
            continue
        try:
            if view is not None:
                await channel.send(embed=embed, view=view)
            else:
                await channel.send(embed=embed)
            results.append({
                "guild_id": str(guild.id), "guild_name": guild.name,
                "status": "sent", "detail": f"#{channel.name}",
            })
        except Exception as e:
            results.append({
                "guild_id": str(guild.id), "guild_name": guild.name,
                "status": "error", "detail": str(e),
            })

    sent = sum(1 for r in results if r["status"] == "sent")
    return web.json_response({"results": results, "sent": sent, "total": len(results)})


async def start_web_server(bot):
    global _runner, _cache
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        return

    hub = SSEHub()
    cache = StatCache(bot, hub)
    await cache.start()
    _cache = cache

    app = web.Application()
    app["bot"] = bot
    app["session_id"] = secrets.token_hex(32)
    app["cache"] = cache
    app["sse_hub"] = hub
    app.router.add_get("/login", _handle_login)
    app.router.add_post("/api/auth", _handle_auth)
    app.router.add_get("/", _require_auth(_handle_index))
    app.router.add_get("/admin", _require_auth(_handle_admin))
    app.router.add_post("/api/admin/command", _require_auth(_handle_admin_command))
    app.router.add_get("/api/stats", _require_auth(_handle_stats))
    app.router.add_get("/api/stats/timeline", _require_auth(_handle_stats_timeline))
    app.router.add_get("/api/stats/recent-events", _require_auth(_handle_recent_events))
    app.router.add_get("/api/stream", _require_auth(_handle_sse))
    app.router.add_get("/api/admin/topgg-votes", _require_auth(_handle_topgg_votes))
    app.router.add_get("/api/admin/guild-list", _require_auth(_handle_guild_list))
    app.router.add_post("/api/admin/broadcast-embed", _require_auth(_handle_broadcast_embed))
    app.router.add_post("/webhooks/topgg", _handle_topgg_webhook)
    app.router.add_static('/static', Path(__file__).parent / 'static', name='static')

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")
