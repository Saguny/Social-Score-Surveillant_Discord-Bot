import asyncio
import io
import time
from collections import OrderedDict

import discord

from .render_scene import render_scene_image

EMBED_COLOR = 0x1a1a2e

# ── Prefetch cache ────────────────────────────────────────────────────────────
# Keyed by (story_id, scene_id, party_tuple) → (timestamp, png_bytes)
_cache: OrderedDict[tuple, tuple[float, bytes]] = OrderedDict()
_CACHE_TTL = 300   # seconds before a cached render expires
_CACHE_MAX = 500   # max entries — ~250MB at 500KB/PNG average


def _cache_key(story_id: str, scene_id: str, party_chars: list) -> tuple:
    ids = tuple(
        (c.get("character_id") if c else None)
        for c in party_chars
    )
    return (story_id, scene_id, ids)


def _cache_get(key: tuple) -> bytes | None:
    entry = _cache.get(key)
    if not entry:
        return None
    if time.monotonic() - entry[0] > _CACHE_TTL:
        del _cache[key]
        return None
    _cache.move_to_end(key)
    return entry[1]


def _cache_set(key: tuple, png: bytes) -> None:
    _cache[key] = (time.monotonic(), png)
    _cache.move_to_end(key)
    while len(_cache) > _CACHE_MAX:
        _cache.popitem(last=False)


async def _prefetch(db, story: dict, scene_id: str, party_chars: list) -> None:
    """Render a scene in the background and store it in the cache."""
    try:
        key = _cache_key(story["id"], scene_id, party_chars)
        if _cache_get(key):
            return
        scene = await db.get_vn_scene(story["id"], scene_id)
        if not scene or scene.get("scene_type") == "router":
            return
        bio = await render_scene_image(db, story, scene, party_chars)
        _cache_set(key, bio.read())
    except Exception:
        pass


def _queue_prefetch(db, story: dict, scene: dict, party_chars: list) -> None:
    """Fire-and-forget prefetch for the next scene(s)."""
    targets: list[str] = []
    if scene.get("next_scene"):
        targets.append(scene["next_scene"])
    for ch in (scene.get("choices") or []):
        for t in (ch.get("pass_scene"), ch.get("fail_scene")):
            if t and t not in targets:
                targets.append(t)
    for t in targets:
        asyncio.create_task(_prefetch(db, story, t, party_chars))


# ── Arc titles ────────────────────────────────────────────────────────────────
# Shown on every scene embed but changes only when an arc is renamed, so it does
# not deserve a DB round-trip per scene delivery.
_ARC_TTL = 300.0
_arc_titles: dict[int, tuple[float, str | None]] = {}


async def _arc_title(db, arc_id: int) -> str | None:
    hit = _arc_titles.get(arc_id)
    if hit and time.monotonic() - hit[0] < _ARC_TTL:
        return hit[1]
    arc   = await db.get_vn_arc(arc_id)
    title = arc.get("title") if arc else None
    _arc_titles[arc_id] = (time.monotonic(), title)
    return title


# ── Public entry point ────────────────────────────────────────────────────────

async def build_scene_render(
    db, story: dict, scene: dict, party_chars: list, reward_text: str | None = None
) -> tuple[discord.File, discord.Embed]:
    """Render the scene (cache-first) and return (File, Embed)."""

    key    = _cache_key(story["id"], scene["id"], party_chars)
    cached = _cache_get(key)

    if cached:
        png_bytes = cached
    else:
        bio       = await render_scene_image(db, story, scene, party_chars)
        png_bytes = bio.read()
        _cache_set(key, png_bytes)

    # kick off background render of the next scene(s)
    _queue_prefetch(db, story, scene, party_chars)

    file = discord.File(io.BytesIO(png_bytes), filename="vn_scene.png")

    arc_title = None
    if story.get("arc_id"):
        arc_title = await _arc_title(db, story["arc_id"])

    scene_type = scene.get("scene_type", "story")
    ep_title   = story["title"]
    if scene_type == "ending":
        et       = (scene.get("ending_type") or "ending").upper()
        ep_title = f"{ep_title} · {et} END"

    embed = discord.Embed(title=ep_title, description=arc_title, color=EMBED_COLOR)
    embed.set_image(url="attachment://vn_scene.png")
    if reward_text:
        embed.add_field(name="REWARD", value=reward_text, inline=False)
    embed.set_footer(text="VN Assets by Noraneko · GLORY TO THE CCP!")

    return file, embed
