import os
import hmac
import time
import secrets
import asyncio
import webbrowser
from pathlib import Path
from aiohttp import web

PORT = int(os.getenv("PORT", 8080))
_runner = None

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
    await bot.close()
    import os as _os
    _os._exit(42)


async def _delayed_shutdown(bot):
    await asyncio.sleep(0.5)
    await bot.close()


async def _handle_topgg_webhook(request):
    secret = os.getenv("TOPGG_WEBHOOK_SECRET", "")
    auth = request.headers.get("Authorization", "")
    if not secret or not hmac.compare_digest(auth, secret):
        return web.Response(status=403)

    try:
        body = await request.json()
    except Exception:
        return web.Response(status=400)

    if body.get("type") != "upvote":
        return web.Response(status=200)

    try:
        user_id = int(body.get("user", 0))
    except (TypeError, ValueError):
        return web.Response(status=400)

    bot = request.app["bot"]
    from cogs.voting import process_vote
    asyncio.create_task(process_vote(bot, user_id))
    return web.Response(status=200)


async def _handle_stats(request):
    bot = request.app["bot"]
    t0 = time.time()
    stats = await bot.db.get_global_stats()
    stats["db_query_ms"]     = round((time.time() - t0) * 1000, 1)
    stats["uptime_seconds"]  = int(time.time() - bot.start_time.timestamp()) if getattr(bot, "start_time", None) else 0
    stats["discord_ping_ms"] = round(bot.latency * 1000, 1) if bot.latency else None
    return web.json_response(stats)


async def _handle_topgg_votes(request):
    bot = request.app["bot"]
    period = request.query.get("period", "7D").upper()
    if period not in ("1D", "7D", "1M", "TOTAL"):
        period = "7D"
    buckets = await bot.db.get_topgg_vote_timeline(period)
    total = sum(row["votes"] for row in buckets)
    return web.json_response({"period": period, "buckets": buckets, "total": total})


async def start_web_server(bot):
    global _runner
    if _runner:
        print(f"Web dashboard already running at http://localhost:{PORT}")
        return

    app = web.Application()
    app["bot"] = bot
    app["session_id"] = secrets.token_hex(32)
    app.router.add_get("/login", _handle_login)
    app.router.add_post("/api/auth", _handle_auth)
    app.router.add_get("/", _require_auth(_handle_index))
    app.router.add_get("/admin", _require_auth(_handle_admin))
    app.router.add_post("/api/admin/command", _require_auth(_handle_admin_command))
    app.router.add_get("/api/stats", _require_auth(_handle_stats))
    app.router.add_get("/api/admin/topgg-votes", _require_auth(_handle_topgg_votes))
    app.router.add_post("/webhooks/topgg", _handle_topgg_webhook)
    app.router.add_static('/static', Path(__file__).parent / 'static', name='static')

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")
