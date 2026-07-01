import os
import hmac
import time
import json
import hashlib
import secrets
import asyncio
import urllib.parse
from pathlib import Path
from aiohttp import web
import aiohttp

from web.cache import StatCache, format_event
from web.sse import SSEHub
from web.anonymize import redact_global_stats, pseudonym_user, pseudonym_guild, using_fallback_salt
from infra.redis_cache import cache_get, cache_set, cache_delete
from infra.admin_rpc import call_admin_rpc, fire_admin_rpc
from infra.guild_notify import publish_guild_notify
from config.achievements import ACHIEVEMENTS
from config.shop import COSMETIC_META
from config.stocks import (
    REAL_STOCKS, ETF_TICKER, ETF_INFO, PENNY_STOCKS,
    ALL_TICKERS, TURBO_MIN_COST, _PERIOD_SECONDS,
    ADR_TICKERS, LSE_TICKERS, TSE_TICKERS, PENNY_TICKERS,
)
from config.market_hours import is_market_hours, all_exchange_status

PORT = int(os.getenv("PORT", 8080))
_runner = None
_cache: StatCache | None = None

LEADERBOARD_LIMIT = 25

_SESSION_TTL         = 60 * 60 * 24 * 30
_DISCORD_SESSION_TTL = 60 * 60 * 24 * 7

_DISCORD_API       = "https://discord.com/api/v10"
_DISCORD_TOKEN_URL = f"{_DISCORD_API}/oauth2/token"
_DISCORD_USER_URL  = f"{_DISCORD_API}/users/@me"

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
            return hops[0]
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


def _discord_redirect_uri(request) -> str:
    base = os.getenv("DISCORD_REDIRECT_URI", "")
    if base:
        return base
    scheme = request.headers.get("X-Forwarded-Proto", "http")
    host   = request.headers.get("X-Forwarded-Host", request.host)
    return f"{scheme}://{host}/auth/discord/callback"


async def _discord_session(request) -> dict | None:
    cookie = request.cookies.get("discord_auth", "")
    if not cookie:
        return None
    raw = await cache_get(f"discordSession:{cookie}")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _require_discord(handler):
    async def middleware(request):
        if not await _discord_session(request):
            raise web.HTTPFound(f"/auth/discord?next={urllib.parse.quote(str(request.rel_url))}")
        return await handler(request)
    return middleware


async def _handle_discord_auth(request):
    client_id    = os.getenv("DISCORD_CLIENT_ID", "")
    redirect_uri = _discord_redirect_uri(request)
    next_url     = request.rel_url.query.get("next", "/account")
    next_safe    = next_url if next_url.startswith("/") else "/account"

    nonce = secrets.token_urlsafe(16)
    await cache_set(f"oauthNonce:{nonce}", next_safe, ex=300)
    state = f"{nonce}.{urllib.parse.quote(next_safe, safe='')}"

    params = urllib.parse.urlencode({
        "client_id":     client_id,
        "redirect_uri":  redirect_uri,
        "response_type": "code",
        "scope":         "identify",
        "state":         state,
    })
    raise web.HTTPFound(f"https://discord.com/api/oauth2/authorize?{params}")


async def _handle_discord_callback(request):
    code  = request.rel_url.query.get("code", "")
    state = request.rel_url.query.get("state", "")
    if not code or not state:
        raise web.HTTPFound("/account")

    nonce, _, encoded_next = state.partition(".")
    fallback = urllib.parse.unquote(encoded_next) if encoded_next else "/account"
    if not fallback.startswith("/"):
        fallback = "/account"

    cached = await cache_get(f"oauthNonce:{nonce}")
    if not cached:
        raise web.HTTPFound(f"{fallback}?error=oauth_expired")
    await cache_delete(f"oauthNonce:{nonce}")
    next_safe = cached.decode() if isinstance(cached, bytes) else cached
    if not next_safe.startswith("/"):
        next_safe = fallback

    client_id     = os.getenv("DISCORD_CLIENT_ID", "")
    client_secret = os.getenv("DISCORD_CLIENT_SECRET", "")
    redirect_uri  = _discord_redirect_uri(request)

    _timeout = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=_timeout) as session:
            async with session.post(_DISCORD_TOKEN_URL, data={
                "client_id":     client_id,
                "client_secret": client_secret,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  redirect_uri,
            }) as resp:
                if resp.status != 200:
                    raise web.HTTPFound(f"{fallback}?error=oauth_failed")
                token_data = await resp.json(content_type=None)

            access_token = token_data.get("access_token", "")
            if not access_token:
                raise web.HTTPFound(f"{fallback}?error=oauth_failed")
            async with session.get(_DISCORD_USER_URL, headers={
                "Authorization": f"Bearer {access_token}"
            }) as resp:
                if resp.status != 200:
                    raise web.HTTPFound(f"{fallback}?error=oauth_failed")
                user = await resp.json(content_type=None)
    except web.HTTPFound:
        raise
    except Exception:
        raise web.HTTPFound(f"{fallback}?error=oauth_failed")

    session_token = secrets.token_hex(32)
    payload = json.dumps({
        "discord_id": int(user["id"]),
        "username":   user.get("username", ""),
        "avatar":     user.get("avatar", ""),
    })
    await cache_set(f"discordSession:{session_token}", payload, ex=_DISCORD_SESSION_TTL)

    response = web.HTTPFound(next_safe)
    response.set_cookie(
        "discord_auth", session_token,
        httponly=True, secure=True, samesite="Lax",
        max_age=_DISCORD_SESSION_TTL,
        path="/",
    )
    raise response


async def _handle_discord_logout(request):
    cookie = request.cookies.get("discord_auth", "")
    if cookie:
        await cache_delete(f"discordSession:{cookie}")
    response = web.HTTPFound("/wishlist")
    response.del_cookie("discord_auth")
    raise response


_WIKI_API = "https://en.wikipedia.org/w/api.php"
_WIKI_UA  = "SocialCreditBot/2.0 (https://discord.gg/invite/k4W6YAPYhC; character request portal)"

_SUBMIT_DAILY_LIMIT = 3
_REQUEST_BODY_LIMIT = 4096

_PERSON_KEYWORDS = {
    "born", "died", "politician", "singer", "actor", "actress", "musician",
    "athlete", "footballer", "player", "director", "writer", "author",
    "artist", "ceo", "president", "prime minister", "general", "soldier",
    "rapper", "producer", "model", "entrepreneur", "scientist", "philosopher",
    "scholar", "king", "queen", "emperor", "empress", "prince", "princess",
    "activist", "comedian", "YouTuber", "streamer", "dancer", "idol",
}


def _normalize_slug(title: str) -> str:
    return title.strip().replace(" ", "_").lower()


def _check_origin(request) -> bool:
    origin = request.headers.get("Origin", "")
    host   = request.headers.get("X-Forwarded-Host", request.host)
    if not origin:
        return True
    parsed = urllib.parse.urlparse(origin)
    return parsed.netloc == host


async def _fetch_wikipedia_preview(slug: str) -> dict | None:
    params = {
        "action":      "query",
        "titles":      slug,
        "prop":        "extracts|pageimages|pageterms",
        "exintro":     1,
        "explaintext": 1,
        "piprop":      "thumbnail",
        "pithumbsize": 300,
        "redirects":   1,
        "format":      "json",
    }
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                _WIKI_API,
                params=params,
                headers={"User-Agent": _WIKI_UA},
                timeout=aiohttp.ClientTimeout(total=8),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
        pages = data.get("query", {}).get("pages", {})
        page = next(iter(pages.values()), {})
        if "missing" in page:
            return None
        description = ""
        terms = page.get("terms", {})
        if isinstance(terms, dict):
            descs = terms.get("description", [])
            description = descs[0] if descs else ""
        return {
            "title":         page.get("title", ""),
            "extract":       (page.get("extract", "") or "")[:500],
            "thumbnail_url": (page.get("thumbnail") or {}).get("source", ""),
            "description":   description,
        }
    except Exception:
        return None


def _looks_like_person(wiki_data: dict) -> bool:
    text = f"{wiki_data.get('description', '')} {wiki_data.get('extract', '')}".lower()
    return any(kw in text for kw in _PERSON_KEYWORDS)


async def _handle_requests_check(request):
    title = request.rel_url.query.get("title", "").strip()
    if not title or len(title) > 200:
        return web.json_response({"state": "invalid"})

    slug = _normalize_slug(title)
    db   = request.app["db"]

    existing_char = await db.find_gacha_character_id(slug.replace("_", " "))
    if existing_char is None:
        existing_char = await db.find_gacha_character_id(slug)
    if existing_char:
        return web.json_response({"state": "in_game", "character_id": existing_char})

    existing_req = await db.get_request_by_slug(slug)
    if existing_req and existing_req.get("status") == "approved":
        return web.json_response({"state": "in_game"})
    if existing_req:
        vote_count, recent_voters, wiki_preview, user_session = await asyncio.gather(
            db.get_vote_count(existing_req["id"]),
            db.get_recent_voters(existing_req["id"], limit=4),
            _fetch_wikipedia_preview(slug),
            _discord_session(request),
        )
        has_voted = False
        if user_session:
            has_voted = await db.has_voted(existing_req["id"], user_session["discord_id"])
        return web.json_response({
            "state":         "requested",
            "request_id":    existing_req["id"],
            "wiki_title":    existing_req["wiki_title"],
            "wiki_slug":     slug,
            "thumbnail_url": (wiki_preview or {}).get("thumbnail_url", ""),
            "description":   (wiki_preview or {}).get("description", ""),
            "submitted_by":  existing_req["discord_username"],
            "submitted_at":  existing_req["submitted_at"],
            "vote_count":    vote_count,
            "recent_voters": recent_voters,
            "has_voted":     has_voted,
        })

    wiki = await _fetch_wikipedia_preview(slug)
    if wiki is None:
        return web.json_response({"state": "not_found"})
    if not _looks_like_person(wiki):
        return web.json_response({"state": "not_person"})

    return web.json_response({
        "state":         "valid",
        "wiki_slug":     slug,
        "wiki_title":    wiki["title"],
        "thumbnail_url": wiki["thumbnail_url"],
        "description":   wiki["description"],
        "extract":       wiki["extract"],
    })


async def _handle_requests_submit(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in."}, status=401)

    if not _check_origin(request):
        return web.json_response({"error": "Forbidden."}, status=403)

    try:
        body = await request.content.read(_REQUEST_BODY_LIMIT + 1)
        if len(body) > _REQUEST_BODY_LIMIT:
            return web.json_response({"error": "Request too large."}, status=413)
        data = json.loads(body)
    except Exception:
        return web.json_response({"error": "Invalid request."}, status=400)

    title = (data.get("title") or "").strip()
    tos   = data.get("tos_confirmed", False)

    if not title or len(title) > 200:
        return web.json_response({"error": "Invalid title."}, status=400)
    if not tos:
        return web.json_response({"error": "TOS confirmation required."}, status=400)

    discord_id = user["discord_id"]
    db = request.app["db"]

    if await db.is_submitter_banned(discord_id):
        return web.json_response({"error": "Your account is not eligible to submit requests."}, status=403)

    count_today = await db.get_user_request_count_today(discord_id)
    if count_today >= _SUBMIT_DAILY_LIMIT:
        return web.json_response({"error": f"Daily limit of {_SUBMIT_DAILY_LIMIT} new requests reached."}, status=429)

    slug = _normalize_slug(title)

    existing_char = await db.find_gacha_character_id(slug.replace("_", " "))
    if existing_char is None:
        existing_char = await db.find_gacha_character_id(slug)
    if existing_char:
        return web.json_response({"error": "already_in_game", "character_id": existing_char}, status=409)

    existing_req = await db.get_request_by_slug(slug)
    if existing_req:
        return web.json_response({"error": "already_requested", "request_id": existing_req["id"]}, status=409)

    wiki = await _fetch_wikipedia_preview(slug)
    if wiki is None:
        return web.json_response({"error": "Wikipedia article not found."}, status=400)
    if not _looks_like_person(wiki):
        return web.json_response({"error": "Article does not appear to be about a real person."}, status=400)

    try:
        request_id = await db.create_request(
            discord_id       = discord_id,
            discord_username = user["username"],
            wiki_slug        = slug,
            wiki_title       = wiki["title"],
            thumbnail_url    = wiki.get("thumbnail_url", ""),
            wiki_extract     = wiki.get("extract", ""),
        )
    except ValueError:
        return web.json_response({"error": "already_requested"}, status=409)

    return web.json_response({"ok": True, "request_id": request_id, "wiki_title": wiki["title"]})


async def _handle_requests_vote(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in."}, status=401)

    if not _check_origin(request):
        return web.json_response({"error": "Forbidden."}, status=403)

    try:
        body = await request.content.read(_REQUEST_BODY_LIMIT)
        data = json.loads(body)
    except Exception:
        return web.json_response({"error": "Invalid request."}, status=400)

    try:
        request_id = int(data.get("request_id", 0))
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid request_id."}, status=400)
    if request_id <= 0:
        return web.json_response({"error": "Invalid request_id."}, status=400)

    db         = request.app["db"]
    discord_id = user["discord_id"]

    req = await db.get_request_by_id(request_id)
    if not req or req["status"] != "pending":
        return web.json_response({"error": "Request not found."}, status=404)

    if await db.has_voted(request_id, discord_id):
        await db.remove_vote(request_id, discord_id)
        voted = False
    else:
        await db.add_vote(request_id, discord_id, user["username"])
        voted = True

    vote_count = await db.get_vote_count(request_id)
    return web.json_response({"ok": True, "voted": voted, "vote_count": vote_count})


async def _handle_requests_delete(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    request_id_raw = body.get("request_id")
    try:
        request_id = int(request_id_raw)
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid request_id"}, status=400)

    db      = request.app["db"]
    deleted = await db.delete_own_request(request_id, user["discord_id"])
    if not deleted:
        return web.json_response({"error": "Request not found or not deletable (only pending requests can be withdrawn)."}, status=404)

    await cache_delete(f"account:{user['discord_id']}")
    return web.json_response({"ok": True})


async def _handle_requests_wishlist(request):
    limit = min(int(request.rel_url.query.get("limit", 20)), 50)
    sort  = request.rel_url.query.get("sort", "votes")
    db    = request.app["db"]

    if sort == "approved":
        rows = await db.get_approved_requests(limit)
        return web.json_response({
            "requests": [
                {
                    "id":           row["id"],
                    "wiki_slug":    row["wiki_slug"],
                    "wiki_title":   row["wiki_title"],
                    "submitted_by": row["discord_username"],
                    "submitted_at": row["submitted_at"],
                    "approved_at":  row.get("reviewed_at"),
                    "thumbnail_url": row.get("thumbnail_url") or "",
                    "wiki_extract": row.get("wiki_extract") or "",
                    "status":       "approved",
                }
                for row in rows
            ],
            "logged_in": False,
        })

    rows    = await db.get_pending_requests(limit=limit, sort=sort if sort == "newest" else "votes")
    user    = await _discord_session(request)
    user_id = user["discord_id"] if user else None

    request_ids = [row["id"] for row in rows]
    if user_id:
        voters_map, voted_set = await asyncio.gather(
            db.get_voters_for_requests(request_ids, voter_limit=4),
            db.get_user_votes_for_requests(user_id, request_ids),
        )
    else:
        voters_map = await db.get_voters_for_requests(request_ids, voter_limit=4)
        voted_set  = set()

    results = [
        {
            "id":            row["id"],
            "wiki_slug":     row["wiki_slug"],
            "wiki_title":    row["wiki_title"],
            "submitted_by":  row["discord_username"],
            "submitted_at":  row["submitted_at"],
            "thumbnail_url": row.get("thumbnail_url") or "",
            "wiki_extract":  row.get("wiki_extract") or "",
            "vote_count":    row["vote_count"],
            "recent_voters": voters_map.get(row["id"], []),
            "has_voted":     row["id"] in voted_set,
            "status":        "pending",
        }
        for row in rows
    ]
    return web.json_response({"requests": results, "logged_in": user_id is not None})


async def _handle_submit_page(request):
    return web.Response(text=_load_template('submit.html'), content_type='text/html')


async def _handle_wishlist_page(request):
    return web.Response(text=_load_template('wishlist.html'), content_type='text/html')


async def _handle_discord_me(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"logged_in": False}, status=401)
    return web.json_response({
        "logged_in": True,
        "id":        str(user["discord_id"]),
        "username":  user["username"],
        "avatar":    user.get("avatar"),
    })


async def _handle_landing(request):
    return web.Response(text=_load_template('landing.html'), content_type='text/html')


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

    cache_key = f"cmd_stats_v3:{range_}"
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


_ROUTES = [
    {"method": "GET",  "path": "/",                                        "auth": "public",  "description": "Landing page"},
    {"method": "GET",  "path": "/dashboard",                               "auth": "public",  "description": "Public dashboard"},
    {"method": "GET",  "path": "/leaderboards",                            "auth": "public",  "description": "Guild leaderboard page"},
    {"method": "GET",  "path": "/submit",                                  "auth": "public",  "description": "Character submission page"},
    {"method": "GET",  "path": "/wishlist",                                "auth": "public",  "description": "Community wishlist / voting page"},
    {"method": "GET",  "path": "/account",                                 "auth": "public",  "description": "User account page"},
    {"method": "GET",  "path": "/privacy",                                 "auth": "public",  "description": "Privacy policy"},
    {"method": "GET",  "path": "/terms",                                   "auth": "public",  "description": "Terms of service"},
    {"method": "GET",  "path": "/robots.txt",                              "auth": "public",  "description": "Robots exclusion file"},
    {"method": "GET",  "path": "/auth/discord",                            "auth": "public",  "description": "Start Discord OAuth2 flow — ?next= sets redirect destination"},
    {"method": "GET",  "path": "/auth/discord/callback",                   "auth": "public",  "description": "Discord OAuth2 callback"},
    {"method": "GET",  "path": "/auth/discord/logout",                     "auth": "public",  "description": "Clear Discord session cookie"},
    {"method": "GET",  "path": "/login",                                   "auth": "admin-ip", "description": "Admin login page"},
    {"method": "POST", "path": "/api/auth",                                "auth": "admin-ip", "description": "Admin password auth — returns session cookie"},
    {"method": "GET",  "path": "/api/routes",                              "auth": "public",  "description": "Lists all API routes as JSON"},
    {"method": "GET",  "path": "/docs",                                    "auth": "public",  "description": "Human-readable API reference page"},
    {"method": "GET",  "path": "/api/discord/me",                          "auth": "discord", "description": "Current Discord user info",
     "fields": "logged_in, id (string snowflake), username, avatar (hash or null)"},
    {"method": "GET",  "path": "/api/stats",                               "auth": "public",  "description": "Global bot stats",
     "fields": "avg_score (float), total_users, total_messages, total_guilds, total_yuan, total_earned, total_spent, dau, wau, highest_score, lowest_score, highest_yuan, avg_msgs_per_user, endorsements, rebukes, checkins_today, checkins_yday, events_24h, pos_24h, neg_24h, net_delta_7d, score_dist {t1–t8}, total_votes, yuan_in_stocks, yuan_in_turbos, treasury_total, top_reasons[], daily_7d[]"},
    {"method": "GET",  "path": "/api/stats/all",                           "auth": "public",  "description": "All stats in one response"},
    {"method": "GET",  "path": "/api/stats/timeline",                      "auth": "public",  "description": "Activity timeline — ?range=24h|7d|30d",
     "fields": "range, buckets[] {ts, messages, score_delta, dau, checkins}"},
    {"method": "GET",  "path": "/api/stats/recent-events",                 "auth": "public",  "description": "Recent score events feed",
     "fields": "events[] {user (pseudonym), delta, timestamp, reason (sanitised)}"},
    {"method": "GET",  "path": "/api/stats/commands",                      "auth": "public",  "description": "Command usage analytics"},
    {"method": "GET",  "path": "/api/leaderboard",                         "auth": "public",  "description": "User leaderboard — ?guild_id="},
    {"method": "GET",  "path": "/api/leaderboards/guilds",                 "auth": "public",  "description": "Guild leaderboard — ?metric=&bracket="},
    {"method": "GET",  "path": "/api/stream",                              "auth": "public",  "description": "Server-Sent Events live feed — events: stats, latency, feed"},
    {"method": "GET",  "path": "/api/announcement",                        "auth": "public",  "description": "Current dashboard announcement",
     "fields": "enabled, message, severity (info|warn|danger), updated_at"},
    {"method": "GET",  "path": "/api/account",                             "auth": "discord", "description": "Account overview — stats, guilds, achievements, badges"},
    {"method": "GET",  "path": "/api/account/portfolio",                   "auth": "discord", "description": "Portfolio holdings, turbos, and full ticker list — ?guild_id="},
    {"method": "GET",  "path": "/api/account/portfolio/history",           "auth": "discord", "description": "Portfolio value history — ?guild_id=&period=1D|5D|1M|6M|1Y"},
    {"method": "GET",  "path": "/api/account/portfolio/turbos/available",  "auth": "discord", "description": "Today's available turbo certificates — ?guild_id="},
    {"method": "GET",  "path": "/api/account/stock/chart",                 "auth": "discord", "description": "Price history for a ticker — ?ticker=&period=1D|5D|1M|6M|1Y"},
    {"method": "POST", "path": "/api/account/portfolio/buy",               "auth": "discord", "description": "Buy shares — {guild_id, ticker, shares}"},
    {"method": "POST", "path": "/api/account/portfolio/sell",              "auth": "discord", "description": "Sell shares — {guild_id, ticker, shares}"},
    {"method": "POST", "path": "/api/account/portfolio/turbo/open",        "auth": "discord", "description": "Open a turbo position — {guild_id, ticker, direction, leverage, cost}"},
    {"method": "POST", "path": "/api/account/portfolio/turbo/close",       "auth": "discord", "description": "Close a turbo position — {guild_id, ticker, turbo_id}"},
    {"method": "GET",  "path": "/api/requests/check",                      "auth": "public",  "description": "Check if a Wikipedia title is already submitted — ?title=",
     "fields": "state (invalid|not_found|not_person|in_game|requested|valid) · in_game→character_id · requested→request_id, vote_count, has_voted, submitted_by · valid→wiki_slug, wiki_title, thumbnail_url, description, extract"},
    {"method": "GET",  "path": "/api/requests/wishlist",                   "auth": "public",  "description": "Pending submissions — ?page=&sort=votes|newest",
     "fields": "requests[] {id, wiki_slug, wiki_title, submitted_by, submitted_at, vote_count, has_voted, recent_voters[]}, logged_in"},
    {"method": "POST", "path": "/api/requests/submit",                     "auth": "discord", "description": "Submit a character — {wiki_title, reason?}"},
    {"method": "POST", "path": "/api/requests/vote",                       "auth": "discord", "description": "Vote on a submission — {request_id}"},
    {"method": "POST", "path": "/api/requests/delete",                     "auth": "discord", "description": "Delete own pending submission — {request_id}"},
    {"method": "GET",  "path": "/api/admin/requests",                      "auth": "admin",   "description": "All pending submissions for review"},
    {"method": "POST", "path": "/api/admin/requests/approve",              "auth": "admin",   "description": "Approve a submission — {request_id}"},
    {"method": "POST", "path": "/api/admin/requests/reject",               "auth": "admin",   "description": "Reject a submission — {request_id, reason?}"},
    {"method": "POST", "path": "/api/admin/requests/ban",                  "auth": "admin",   "description": "Ban a user from submitting — {user_id}"},
    {"method": "POST", "path": "/api/admin/requests/edit",                 "auth": "admin",   "description": "Edit submission fields before approval — {request_id, ...fields}"},
    {"method": "GET",  "path": "/api/admin/topgg-votes",                   "auth": "admin",   "description": "Top.gg vote timeline — ?period=1D|7D|1M|TOTAL"},
    {"method": "GET",  "path": "/api/admin/guild-list",                    "auth": "admin",   "description": "All guilds the bot is in"},
    {"method": "GET",  "path": "/api/admin/user-lookup",                   "auth": "admin",   "description": "Look up a user across guilds — ?user_id="},
    {"method": "POST", "path": "/api/admin/user-yuan-adjust",              "auth": "admin",   "description": "Adjust a user's yuan — {guild_id, user_id, amount}"},
    {"method": "POST", "path": "/api/admin/broadcast-embed",               "auth": "admin",   "description": "Send an embed to one or all guilds — {target, title, description, ...}"},
    {"method": "POST", "path": "/api/admin/announcement",                  "auth": "admin",   "description": "Set dashboard announcement — {enabled, message, severity}"},
    {"method": "POST", "path": "/api/admin/command",                       "auth": "admin",   "description": "Run a bot console command — {command}"},
    {"method": "POST", "path": "/webhooks/topgg",                          "auth": "webhook", "description": "Top.gg vote webhook — authenticated via TOPGG_WEBHOOK_SECRET header"},
]


async def _handle_routes(request):
    return web.json_response({"routes": _ROUTES})


_AUTH_COLORS = {
    "public":   ("#7d9d9c", "Public"),
    "discord":  ("#5865f2", "Discord login"),
    "admin":    ("#e85350", "Admin"),
    "admin-ip": ("#e8a250", "Admin IP"),
    "webhook":  ("#8b5cf6", "Webhook"),
}

_METHOD_COLORS = {"GET": "#26a69a", "POST": "#e8a250"}

async def _handle_docs(request):
    groups: dict[str, list] = {}
    for r in _ROUTES:
        section = r["path"].split("/")[1] or "pages"
        groups.setdefault(section, []).append(r)

    rows = ""
    for section, routes in groups.items():
        rows += f'<tr><td colspan="4" class="section">{section.upper()}</td></tr>\n'
        for r in routes:
            color, label = _AUTH_COLORS.get(r["auth"], ("#888", r["auth"]))
            mc = _METHOD_COLORS.get(r["method"], "#aaa")
            fields_html = ""
            if r.get("fields"):
                fields_html = f'<div class="fields">{r["fields"]}</div>'
            rows += (
                f'<tr>'
                f'<td><span class="method" style="color:{mc}">{r["method"]}</span></td>'
                f'<td><code>{r["path"]}</code></td>'
                f'<td><span class="badge" style="border-color:{color};color:{color}">{label}</span></td>'
                f'<td class="desc">{r["description"]}{fields_html}</td>'
                f'</tr>\n'
            )

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="robots" content="noindex,nofollow">
<title>API Docs · Social Credit</title>
<style>
  body {{ font-family: monospace; background: #0e0e10; color: #c9c9c9; margin: 0; padding: 2rem; }}
  h1 {{ color: #e6e6e6; font-size: 1.1rem; letter-spacing: 2px; text-transform: uppercase; margin-bottom: .25rem; }}
  p.sub {{ color: #666; font-size: .8rem; margin-bottom: 2rem; }}
  a {{ color: #7d9d9c; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .82rem; }}
  td {{ padding: .45rem .75rem; border-bottom: 1px solid #1e1e22; vertical-align: middle; }}
  td.section {{ color: #555; font-size: .65rem; letter-spacing: 2px; padding-top: 1.2rem; padding-bottom: .3rem; border-bottom: 1px solid #2a2a2e; }}
  td.desc {{ color: #888; }}
  code {{ background: #1a1a1e; padding: .15rem .4rem; border-radius: 3px; color: #c9c9c9; }}
  .method {{ font-weight: 700; font-size: .78rem; letter-spacing: .5px; }}
  .badge {{ border: 1px solid; border-radius: 3px; font-size: .65rem; padding: .1rem .4rem; letter-spacing: .5px; text-transform: uppercase; white-space: nowrap; }}
  .fields {{ color: #555; font-size: .72rem; margin-top: .3rem; line-height: 1.5; }}
</style>
</head>
<body>
<h1>社会信用 API Reference</h1>
<p class="sub">Machine-readable version: <a href="/api/routes">/api/routes</a></p>
<table>
{rows}
</table>
</body>
</html>"""
    return web.Response(text=html, content_type="text/html")


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


async def _handle_admin_requests(request):
    db   = request.app["db"]
    sort = request.rel_url.query.get("sort", "votes")
    if sort not in ("votes", "newest"):
        sort = "votes"
    rows = await db.get_pending_requests(limit=50, sort=sort)
    return web.json_response({"requests": [dict(r) for r in rows]})


async def _handle_admin_requests_reject(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    request_id = body.get("request_id")
    reason     = str(body.get("reason") or "")[:500]
    if not isinstance(request_id, int) or isinstance(request_id, bool):
        return web.json_response({"error": "request_id required"}, status=400)

    db  = request.app["db"]
    req = await db.get_request_by_id(request_id)
    if not req:
        return web.json_response({"error": "Not found"}, status=404)

    await db.set_request_status(request_id, "rejected", rejection_reason=reason or None)

    if req.get("discord_id"):
        asyncio.create_task(fire_admin_rpc("dm_user", {
            "user_id": req["discord_id"],
            "message": f"Your character request **{req['wiki_title']}** was not approved for the gacha pool."
                       + (f"\n\nReason: {reason}" if reason else ""),
        }))

    return web.json_response({"ok": True})


async def _handle_admin_requests_ban(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    discord_id = body.get("discord_id")
    if not isinstance(discord_id, int):
        return web.json_response({"error": "discord_id required"}, status=400)

    db = request.app["db"]
    await db.ban_submitter(discord_id)
    return web.json_response({"ok": True})


async def _handle_admin_requests_edit(request):
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    request_id = body.get("request_id")
    if not isinstance(request_id, int) or isinstance(request_id, bool):
        return web.json_response({"error": "request_id required"}, status=400)

    rarity     = body.get("rarity") or None
    gender     = body.get("gender") or None
    faction    = body.get("faction") or None
    image_urls = [str(u).strip() for u in (body.get("image_urls") or []) if str(u).strip()]

    _VALID_RARITIES = {"legendary", "epic", "rare", "uncommon", "common"}
    _VALID_GENDERS  = {"male", "female", "other"}
    _VALID_FACTIONS = {"reds", "strongmen", "conquerors", "icons", "wildcards"}
    if rarity and rarity not in _VALID_RARITIES:
        return web.json_response({"error": "Invalid rarity"}, status=400)
    if gender and gender not in _VALID_GENDERS:
        return web.json_response({"error": "Invalid gender"}, status=400)
    if faction and faction not in _VALID_FACTIONS:
        return web.json_response({"error": "Invalid faction"}, status=400)

    db  = request.app["db"]
    req = await db.get_request_by_id(request_id)
    if not req:
        return web.json_response({"error": "Not found"}, status=404)

    await db.update_request_overrides(request_id, rarity, gender, image_urls, faction)
    return web.json_response({"ok": True})


async def _handle_admin_requests_approve(request):
    """SSE endpoint — streams approval pipeline stages to the admin panel."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    request_id  = body.get("request_id")
    if not isinstance(request_id, int) or isinstance(request_id, bool):
        return web.json_response({"error": "request_id required"}, status=400)

    db  = request.app["db"]
    req = await db.get_request_by_id(request_id)
    if not req:
        return web.json_response({"error": "Not found"}, status=404)
    if req["status"] != "pending":
        return web.json_response({"error": "Request is not pending"}, status=409)

    response = web.StreamResponse(headers={
        "Content-Type":  "text/event-stream",
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })
    await response.prepare(request)

    async def emit(stage: str, msg: str, ok: bool = True):
        payload = json.dumps({"stage": stage, "msg": msg, "ok": ok})
        await response.write(f"data: {payload}\n\n".encode())

    wiki_slug = req["wiki_slug"]

    try:
        # Stage 1 — fetch Wikipedia data
        await emit("wiki", "Fetching Wikipedia article…")
        wiki = await _fetch_wikipedia_preview(wiki_slug)
        if wiki is None:
            await emit("wiki", "Wikipedia article not found. Approve anyway? Skipping enrichment.", ok=False)
            wiki_title = req["wiki_title"]
        else:
            wiki_title = wiki["title"]
            await emit("wiki", f"Found: {wiki_title}")

        # Stage 2 — run gacha pipeline (image scrape, stat generation)
        await emit("pipeline", "Running gacha enrichment pipeline…")
        try:
            from gacha.pipeline import process_slug
            char_data = await process_slug(wiki_slug)
        except Exception as exc:
            await emit("pipeline", f"Pipeline error: {exc}. Saving with minimal data.", ok=False)
            char_data = None

        if char_data:
            await emit("pipeline", f"Pipeline complete — {len(char_data.get('image_urls', []))} image(s) found.")
        else:
            await emit("pipeline", "Using minimal character entry (no enrichment).")

        # Stage 3 — save to database
        await emit("db", "Saving character to database…")
        char_id = wiki_slug.lower().replace(" ", "_")
        data_to_save = char_data or {
            "name":       wiki_title,
            "title":      "",
            "faction":    "wildcards",
            "rarity":     "common",
            "quote":      "",
            "wiki":       wiki_slug,
            "gender":     None,
            "image_urls": [],
            "stats":      {"authority": 50, "military": 50, "charisma": 50},
        }
        if req.get("override_rarity"):
            data_to_save["rarity"] = req["override_rarity"]
        if req.get("override_gender"):
            data_to_save["gender"] = req["override_gender"]
        if req.get("override_faction"):
            data_to_save["faction"] = req["override_faction"]
        if req.get("override_image_urls"):
            data_to_save["image_urls"] = list(req["override_image_urls"])

        await db.upsert_gacha_character(
            character_id            = char_id,
            data                    = data_to_save,
            submitted_by_discord_id = req.get("discord_id"),
            submitted_by_username   = req.get("discord_username"),
        )
        await publish_guild_notify(0, "reload_gacha", {})
        first_approval = await db.set_request_approved_atomic(request_id)
        await emit("db", f"Saved as `{char_id}`.")

        if first_approval:
            # Increment contributor counter for milestone achievements
            submitter_discord_id = req.get("discord_id")
            if submitter_discord_id:
                new_count = await db.increment_counter(submitter_discord_id, "gacha_contributions")
                asyncio.create_task(fire_admin_rpc("check_contribution_milestone", {
                    "user_id":       submitter_discord_id,
                    "contributions": new_count,
                }))

            # Stage 4 — notify voters
            voter_ids = await db.get_request_voters_for_dm(request_id)
            await emit("notify", f"Notifying {len(voter_ids)} voter(s)…")
            for uid in voter_ids:
                asyncio.create_task(fire_admin_rpc("dm_user", {
                    "user_id": uid,
                    "message": f"🎉 A character you supported — **{wiki_title}** — has been approved and added to the Social Credit gacha pool! It may take up to 10 minutes to appear in the bot.",
                }))
            submitter_id = req.get("discord_id")
            if submitter_id and submitter_id not in voter_ids:
                asyncio.create_task(fire_admin_rpc("dm_user", {
                    "user_id": submitter_id,
                    "message": f"🎉 Your character suggestion **{wiki_title}** has been approved and added to the Social Credit gacha pool! It will be credited as suggested by you. It may take up to 10 minutes to appear in the bot.",
                }))
        else:
            await emit("notify", "Already approved — skipping notifications.")
        await emit("notify", "Notifications dispatched.")

        # Stage 5 — done
        await emit("done", f"✓ {wiki_title} is now in the gacha pool.", ok=True)

    except Exception as exc:
        await emit("error", f"Unexpected error: {exc}", ok=False)

    return response


_ACCOUNT_COUNTER_KEYS = [
    "checkin:streak",
    "topgg_votes_total", "topgg_vote_streak:current",
    "prestige_level", "gacha_contributions",
]


async def _handle_account_page(request):
    user = await _discord_session(request)
    if not user:
        raise web.HTTPFound("/auth/discord?next=/account")
    return web.Response(text=_load_template("account.html"), content_type="text/html")


async def _handle_account_api(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    user_id = user["discord_id"]
    cache_key = f"account:{user_id}"
    cached = await cache_get(cache_key)
    if cached:
        return web.json_response(json.loads(cached))

    db = request.app["db"]
    guild_data, req_data, ach_data, raw_badges, badge_pref, counters, best_streak_row = await asyncio.gather(
        db.get_user_all_guilds(user_id),
        db.get_user_requests_with_votes(user_id),
        db.get_unlocked_achievements(user_id),
        db.get_cosmetic_badges(user_id),
        db.get_badge_preference(user_id),
        db.get_user_counters(user_id, _ACCOUNT_COUNTER_KEYS),
        db._pool.fetchrow(
            "SELECT MAX(longest_checkin_streak) AS best FROM users WHERE user_id = $1",
            user_id,
        ),
    )

    achievements = [
        {
            "achievement_id": a["achievement_id"],
            "unlocked_at":    a["unlocked_at"],
            "name":           ACHIEVEMENTS.get(a["achievement_id"], {}).get("name", a["achievement_id"]),
            "description":    ACHIEVEMENTS.get(a["achievement_id"], {}).get("description", ""),
            "tier":           ACHIEVEMENTS.get(a["achievement_id"], {}).get("tier", "silent"),
        }
        for a in ach_data
    ]
    achievements.sort(key=lambda a: a["unlocked_at"], reverse=True)

    badges = [
        {
            "id":    b,
            "label": COSMETIC_META.get(b, {}).get("label", b.upper()),
            "color": COSMETIC_META.get(b, {}).get("color", 0x7D9D9C),
            "note":  COSMETIC_META.get(b, {}).get("note", ""),
        }
        for b in raw_badges
    ]

    data = {
        "discord": {
            "id":       str(user_id),
            "username": user["username"],
            "avatar":   user.get("avatar"),
        },
        "counters": {
            "checkin_streak":      counters.get("checkin:streak", 0),
            "checkin_best":        int(best_streak_row["best"] or 0) if best_streak_row else 0,
            "vote_total":          counters.get("topgg_votes_total", 0),
            "vote_streak":         counters.get("topgg_vote_streak:current", 0),
            "prestige_level":      counters.get("prestige_level", 0),
            "gacha_contributions": counters.get("gacha_contributions", 0),
        },
        "guilds": [
            {
                "guild_id":   str(g["guild_id"]),
                "score":      float(g["score"]),
                "yuan":       int(g["yuan"]),
                "rank":       g["rank"],
                "guild_name": g["guild_name"],
            }
            for g in guild_data
        ],
        "requests": [
            {
                "id":          r["id"],
                "wiki_title":  r["wiki_title"],
                "wiki_slug":   r["wiki_slug"],
                "status":      r["status"],
                "submitted_at": r["submitted_at"],
                "vote_count":  int(r["vote_count"]),
            }
            for r in req_data
        ],
        "achievements": achievements,
        "badges":       badges,
        "badge_preference": badge_pref,
    }

    await cache_set(cache_key, json.dumps(data), ex=60)
    return web.json_response(data)


# ── Portfolio helpers ──────────────────────────────────────────────────────────

def _stock_name(ticker: str) -> str:
    if ticker in REAL_STOCKS: return REAL_STOCKS[ticker]["name"]
    if ticker == ETF_TICKER:  return ETF_INFO["name"]
    return PENNY_STOCKS.get(ticker, {}).get("name", ticker)

def _stock_exchange(ticker: str) -> str:
    info = REAL_STOCKS.get(ticker)
    return info["exchange"] if info else "NYSE"

def _turbo_value_factor(direction: str, entry: float, knockout: float, current: float) -> float:
    if direction == "LONG":
        return (current - knockout) / (entry - knockout)
    return (knockout - current) / (knockout - entry)


async def _handle_portfolio_data(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    guild_id_str = request.rel_url.query.get("guild_id", "")
    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    db       = request.app["db"]

    holdings, positions, prices_rows, user_row = await asyncio.gather(
        db.get_portfolio(guild_id, user_id),
        db.get_open_turbo_positions(guild_id, user_id),
        db._pool.fetch("SELECT ticker, price FROM stocks"),
        db._pool.fetchrow(
            "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2",
            guild_id, user_id,
        ),
    )

    if not user_row:
        return web.json_response({"error": "Not a member of this server"}, status=403)

    prices = {r["ticker"]: float(r["price"]) for r in prices_rows}

    holdings_out = []
    for h in holdings:
        ticker    = h["ticker"]
        cur       = prices.get(ticker, float(h["avg_cost"]))
        avg_cost  = float(h["avg_cost"])
        shares    = float(h["shares"])
        value     = cur * shares
        cost_val  = avg_cost * shares
        pnl       = value - cost_val
        pnl_pct   = (pnl / cost_val * 100) if cost_val > 0 else 0.0
        holdings_out.append({
            "ticker":        ticker,
            "name":          _stock_name(ticker),
            "exchange":      _stock_exchange(ticker),
            "shares":        shares,
            "avg_cost":      round(avg_cost, 4),
            "current_price": round(cur, 4),
            "value":         int(value),
            "pnl":           int(pnl),
            "pnl_pct":       round(pnl_pct, 2),
        })

    turbos_out = []
    for p in positions:
        ticker   = p["ticker"]
        cur      = prices.get(ticker, float(p["entry_price"]))
        entry    = float(p["entry_price"])
        knockout = float(p["knockout"])
        factor   = max(0.0, _turbo_value_factor(p["direction"], entry, knockout, cur))
        cost     = int(p["cost"])
        value    = max(0, int(cost * factor))
        turbos_out.append({
            "position_id":   p["position_id"],
            "turbo_id":      p["turbo_id"],
            "ticker":        ticker,
            "name":          _stock_name(ticker),
            "direction":     p["direction"],
            "leverage":      p["leverage"],
            "entry_price":   round(entry, 4),
            "knockout":      round(knockout, 4),
            "current_price": round(cur, 4),
            "cost":          cost,
            "value":         value,
            "pnl":           value - cost,
        })

    held_shares = {h["ticker"]: float(h["shares"]) for h in holdings}

    market_status = all_exchange_status()

    ticker_groups = [
        ("NYSE",  ADR_TICKERS),
        ("LSE",   LSE_TICKERS),
        ("TSE",   TSE_TICKERS),
        ("BSE",   [ETF_TICKER]),
        ("Penny", PENNY_TICKERS),
    ]
    all_tickers_out = []
    for exchange_label, tickers in ticker_groups:
        for t in tickers:
            ex = _stock_exchange(t)
            all_tickers_out.append({
                "ticker":        t,
                "name":          _stock_name(t),
                "exchange":      ex,
                "exchange_label": exchange_label,
                "current_price": round(prices.get(t, 0.0), 4),
                "owned_shares":  held_shares.get(t, 0.0),
            })

    return web.json_response({
        "yuan":        int(user_row["yuan"]),
        "holdings":    holdings_out,
        "turbos":      turbos_out,
        "market":      market_status,
        "all_tickers": all_tickers_out,
    })


async def _handle_portfolio_history(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    guild_id_str = request.rel_url.query.get("guild_id", "")
    period       = request.rel_url.query.get("period", "1D").upper()
    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)
    if period not in _PERIOD_SECONDS:
        period = "1D"

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    since    = int(time.time()) - _PERIOD_SECONDS[period]
    db       = request.app["db"]

    rows = await db.get_portfolio_history(guild_id, user_id, since)
    return web.json_response({
        "period": period,
        "points": [{"ts": r["ts"], "value": int(r["value"])} for r in rows],
    })


async def _handle_stock_chart(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    ticker = request.rel_url.query.get("ticker", "").upper()
    period = request.rel_url.query.get("period", "1D").upper()
    if ticker not in ALL_TICKERS:
        return web.json_response({"error": "Unknown ticker"}, status=400)
    if period not in _PERIOD_SECONDS:
        period = "1D"

    since = int(time.time()) - _PERIOD_SECONDS[period]
    db    = request.app["db"]

    rows, price_row = await asyncio.gather(
        db.get_price_history(ticker, since),
        db._pool.fetchrow("SELECT price FROM stocks WHERE ticker = $1", ticker),
    )
    current = float(price_row["price"]) if price_row else None

    return web.json_response({
        "ticker":        ticker,
        "period":        period,
        "current_price": current,
        "points":        [{"ts": r["ts"], "close": float(r["close"])} for r in rows],
    })


async def _handle_portfolio_turbos_available(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    db    = request.app["db"]
    today = int(time.time()) // 86400
    rows, prices_rows = await asyncio.gather(
        db.get_daily_turbos(today),
        db._pool.fetch("SELECT ticker, price FROM stocks"),
    )
    prices = {r["ticker"]: float(r["price"]) for r in prices_rows}

    return web.json_response({
        "turbos": [
            {
                "id":            r["id"],
                "ticker":        r["ticker"],
                "name":          _stock_name(r["ticker"]),
                "exchange":      _stock_exchange(r["ticker"]),
                "direction":     r["direction"],
                "leverage":      r["leverage"],
                "entry_price":   round(float(r["entry_price"]), 4),
                "knockout":      round(float(r["knockout"]), 4),
                "current_price": round(prices.get(r["ticker"], float(r["entry_price"])), 4),
            }
            for r in rows
        ],
        "min_cost": TURBO_MIN_COST,
        "market":   all_exchange_status(),
    })


async def _handle_portfolio_buy(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    guild_id_str = str(body.get("guild_id", ""))
    ticker       = str(body.get("ticker", "")).upper()
    shares_raw   = body.get("shares")

    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)
    if ticker not in ALL_TICKERS:
        return web.json_response({"error": "Unknown ticker"}, status=400)
    try:
        shares = float(shares_raw)
        if shares <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid shares"}, status=400)

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    exchange = _stock_exchange(ticker)
    if not is_market_hours(exchange):
        return web.json_response({"error": f"{exchange} is closed right now."}, status=400)

    db     = request.app["db"]
    result = await db.buy_stock(guild_id, user_id, ticker, shares)
    if result is None:
        return web.json_response({"error": "Insufficient yuan or price unavailable"}, status=400)

    price      = result["price"]
    total_cost = result["total_cost"]
    new_row = await db._pool.fetchrow(
        "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id,
    )
    return web.json_response({
        "ok":         True,
        "ticker":     ticker,
        "shares":     shares,
        "price":      round(price, 4),
        "total_cost": total_cost,
        "new_yuan":   int(new_row["yuan"]) if new_row else 0,
    })


async def _handle_portfolio_sell(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    guild_id_str = str(body.get("guild_id", ""))
    ticker       = str(body.get("ticker", "")).upper()
    shares_raw   = body.get("shares")

    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)
    if ticker not in ALL_TICKERS:
        return web.json_response({"error": "Unknown ticker"}, status=400)
    try:
        shares = float(shares_raw)
        if shares <= 0:
            raise ValueError
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid shares"}, status=400)

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    exchange = _stock_exchange(ticker)
    if not is_market_hours(exchange):
        return web.json_response({"error": f"{exchange} is closed right now."}, status=400)

    db        = request.app["db"]
    price_row = await db._pool.fetchrow("SELECT price FROM stocks WHERE ticker = $1", ticker)
    if not price_row:
        return web.json_response({"error": "Price unavailable"}, status=400)

    price  = float(price_row["price"])
    result = await db.sell_stock(guild_id, user_id, ticker, shares, price)
    if result is None:
        return web.json_response({"error": "Insufficient shares or position not found"}, status=400)

    new_row = await db._pool.fetchrow(
        "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id,
    )
    return web.json_response({
        "ok":       True,
        "ticker":   ticker,
        "shares":   shares,
        "price":    round(price, 4),
        "proceeds": result["proceeds"],
        "pnl":      result["pnl"],
        "new_yuan": int(new_row["yuan"]) if new_row else 0,
    })


async def _handle_portfolio_turbo_open(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    guild_id_str = str(body.get("guild_id", ""))
    turbo_id_raw = body.get("turbo_id")
    cost_raw     = body.get("cost")

    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)
    try:
        turbo_id = int(turbo_id_raw)
        cost     = int(cost_raw)
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid parameters"}, status=400)
    if cost < TURBO_MIN_COST:
        return web.json_response({"error": f"Minimum investment ¥{TURBO_MIN_COST:,}"}, status=400)

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    db       = request.app["db"]

    turbo = await db.get_turbo(turbo_id)
    if not turbo:
        return web.json_response({"error": "Turbo not found"}, status=404)

    today = int(time.time()) // 86400
    if int(turbo["day"]) != today:
        return web.json_response({"error": "This turbo has expired."}, status=400)

    exchange = _stock_exchange(turbo["ticker"])
    if not is_market_hours(exchange):
        return web.json_response({"error": f"{exchange} is closed right now."}, status=400)

    ok = await db.open_turbo_position(guild_id, user_id, turbo_id, cost)
    if not ok:
        return web.json_response({"error": "Insufficient yuan"}, status=400)

    new_row = await db._pool.fetchrow(
        "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id,
    )
    return web.json_response({
        "ok":       True,
        "turbo_id": turbo_id,
        "cost":     cost,
        "new_yuan": int(new_row["yuan"]) if new_row else 0,
    })


async def _handle_portfolio_turbo_close(request):
    user = await _discord_session(request)
    if not user:
        return web.json_response({"error": "Not logged in"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    guild_id_str    = str(body.get("guild_id", ""))
    position_id_raw = body.get("position_id")

    if not guild_id_str.isdigit():
        return web.json_response({"error": "Invalid guild_id"}, status=400)
    try:
        position_id = int(position_id_raw)
    except (TypeError, ValueError):
        return web.json_response({"error": "Invalid position_id"}, status=400)

    guild_id = int(guild_id_str)
    user_id  = user["discord_id"]
    db       = request.app["db"]

    row = await db.get_turbo_position(guild_id, user_id, position_id)
    if not row or row["status"] != "open":
        return web.json_response({"error": "Position not found or already closed."}, status=404)

    turbo = await db.get_turbo(int(row["turbo_id"]))
    if not turbo:
        return web.json_response({"error": "Turbo data missing."}, status=500)

    exchange = _stock_exchange(turbo["ticker"])
    if not is_market_hours(exchange):
        return web.json_response({"error": f"{exchange} is closed right now."}, status=400)

    price_row = await db._pool.fetchrow("SELECT price FROM stocks WHERE ticker = $1", turbo["ticker"])
    current   = float(price_row["price"]) if price_row else float(turbo["entry_price"])
    entry     = float(turbo["entry_price"])
    knockout  = float(turbo["knockout"])
    factor    = max(0.0, _turbo_value_factor(turbo["direction"], entry, knockout, current))
    proceeds  = max(0, int(int(row["cost"]) * factor))
    pnl       = proceeds - int(row["cost"])

    closed = await db.close_turbo_position(position_id, pnl, "closed")
    if not closed:
        return web.json_response({"error": "Position already closed."}, status=409)
    await asyncio.gather(
        db.add_yuan(guild_id, user_id, proceeds),
        db.update_turbo_stats(guild_id, user_id, knocked=False, pnl=pnl),
    )

    new_row = await db._pool.fetchrow(
        "SELECT yuan FROM users WHERE guild_id = $1 AND user_id = $2", guild_id, user_id,
    )
    return web.json_response({
        "ok":       True,
        "proceeds": proceeds,
        "pnl":      pnl,
        "new_yuan": int(new_row["yuan"]) if new_row else 0,
    })


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
    app.router.add_get("/auth/discord",          _handle_discord_auth)
    app.router.add_get("/auth/discord/callback", _handle_discord_callback)
    app.router.add_get("/auth/discord/logout",   _handle_discord_logout)
    app.router.add_get("/api/discord/me",        _handle_discord_me)
    app.router.add_get("/submit",                _rate_limit_public(_handle_submit_page))
    app.router.add_get("/wishlist",              _rate_limit_public(_handle_wishlist_page))
    app.router.add_get("/api/requests/check",    _rate_limit_public(_handle_requests_check))
    app.router.add_post("/api/requests/submit",  _rate_limit_public(_handle_requests_submit))
    app.router.add_post("/api/requests/vote",    _rate_limit_public(_handle_requests_vote))
    app.router.add_post("/api/requests/delete",  _rate_limit_public(_handle_requests_delete))
    app.router.add_get("/api/requests/wishlist", _rate_limit_public(_handle_requests_wishlist))
    app.router.add_get("/login", _require_admin_ip(_handle_login))
    app.router.add_post("/api/auth", _require_admin_ip(_handle_auth))
    app.router.add_get("/",             _rate_limit_public(_handle_landing))
    app.router.add_get("/dashboard",    _rate_limit_public(_handle_index))
    app.router.add_get("/privacy", _rate_limit_public(_handle_privacy))
    app.router.add_get("/terms",   _rate_limit_public(_handle_terms))
    app.router.add_get("/leaderboards", _rate_limit_public(_handle_leaderboards_page))
    app.router.add_get("/admin", _require_admin(_handle_admin))
    app.router.add_post("/api/admin/command", _require_admin(_handle_admin_command))
    app.router.add_get("/api/routes", _rate_limit_public(_handle_routes))
    app.router.add_get("/docs",       _rate_limit_public(_handle_docs))
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
    app.router.add_post("/api/admin/announcement",        _require_admin(_handle_admin_announcement_set))
    app.router.add_get("/api/admin/requests",             _require_admin(_handle_admin_requests))
    app.router.add_post("/api/admin/requests/approve",    _require_admin(_handle_admin_requests_approve))
    app.router.add_post("/api/admin/requests/reject",     _require_admin(_handle_admin_requests_reject))
    app.router.add_post("/api/admin/requests/ban",        _require_admin(_handle_admin_requests_ban))
    app.router.add_post("/api/admin/requests/edit",       _require_admin(_handle_admin_requests_edit))
    app.router.add_get("/account",      _rate_limit_public(_handle_account_page))
    app.router.add_get("/api/account",  _rate_limit_public(_handle_account_api))
    app.router.add_get("/api/account/portfolio",                  _rate_limit_public(_handle_portfolio_data))
    app.router.add_get("/api/account/portfolio/history",          _rate_limit_public(_handle_portfolio_history))
    app.router.add_get("/api/account/portfolio/turbos/available", _rate_limit_public(_handle_portfolio_turbos_available))
    app.router.add_get("/api/account/stock/chart",                _rate_limit_public(_handle_stock_chart))
    app.router.add_post("/api/account/portfolio/buy",             _rate_limit_public(_handle_portfolio_buy))
    app.router.add_post("/api/account/portfolio/sell",            _rate_limit_public(_handle_portfolio_sell))
    app.router.add_post("/api/account/portfolio/turbo/open",      _rate_limit_public(_handle_portfolio_turbo_open))
    app.router.add_post("/api/account/portfolio/turbo/close",     _rate_limit_public(_handle_portfolio_turbo_close))
    app.router.add_post("/webhooks/topgg", _handle_topgg_webhook)
    app.router.add_get("/robots.txt", _handle_robots)
    app.router.add_static('/static', Path(__file__).parent / 'static', name='static')

    if using_fallback_salt():
        print("[web] WARNING: PSEUDONYM_SALT is not set - public stats are using a default, predictable salt. Set PSEUDONYM_SALT to a random secret.")
    if not os.getenv("ADMIN_ALLOWED_IPS"):
        print("[web] WARNING: ADMIN_ALLOWED_IPS is not set - /admin is reachable from any IP (still token-gated).")

    _runner = web.AppRunner(app)
    await _runner.setup()
    site = web.TCPSite(_runner, "0.0.0.0", PORT)
    await site.start()
    print(f"Web dashboard running on port {PORT}")
