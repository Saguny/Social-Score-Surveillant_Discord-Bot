"""
Standalone VN scene editor.

    python -m scripts.vn_editor.server

Needs DATABASE_URL (or VN_DATABASE_URL) for the story/scene tables, and
R2_TOKEN / R2_ACCOUNT_ID / R2_BUCKET / R2_PUBLIC_URL for background and UI
asset uploads. Runs independently of the bot — no DISCORD_TOKEN, no Redis.
"""
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

from aiohttp import web

from .config import DATABASE_URL, HOST, PORT
from .db import close_pool, get_pool
from .routes import backgrounds, characters, portability, scenes, stories, upload
from .routes import config as config_routes

STATIC_DIR = Path(__file__).parent / "static"
INDEX_FILE = STATIC_DIR / "index.html"

MAX_UPLOAD_BYTES = 32 * 1024 * 1024


async def _index(request):
    return web.FileResponse(INDEX_FILE)


async def _root(request):
    raise web.HTTPFound("/vn")


async def _on_startup(app):
    await get_pool()


async def _on_cleanup(app):
    await close_pool()


def build_app() -> web.Application:
    app = web.Application(client_max_size=MAX_UPLOAD_BYTES)

    for module in (stories, scenes, portability, backgrounds, characters, upload, config_routes):
        app.add_routes(module.routes)

    app.router.add_get("/", _root)
    app.router.add_get("/vn", _index)
    app.router.add_get("/vn/", _index)
    app.router.add_static("/vn/static", STATIC_DIR)

    app.on_startup.append(_on_startup)
    app.on_cleanup.append(_on_cleanup)
    return app


def main() -> None:
    if not DATABASE_URL:
        raise SystemExit("DATABASE_URL (or VN_DATABASE_URL) is not set")
    print(f"[vn-editor] http://{HOST}:{PORT}/vn")
    web.run_app(build_app(), host=HOST, port=PORT, print=None)


if __name__ == "__main__":
    main()
