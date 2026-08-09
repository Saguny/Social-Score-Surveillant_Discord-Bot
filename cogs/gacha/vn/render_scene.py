"""
VN scene renderer — delegates to render_node.js via a persistent subprocess pool.
Each worker is a long-lived `node render_node.js` process; requests are serialised
per-worker so the pool handles N concurrent renders with zero startup overhead.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import re
import struct
from pathlib import Path
from typing import Optional

_NODE_SCRIPT = Path(__file__).parent / "render_node.js"
_POOL_SIZE   = int(os.environ.get("VN_RENDER_WORKERS", str(min((os.cpu_count() or 2) * 2, 16))))

_VN_CONFIG_DEFAULTS = dict(
    speaker_dx=0, speaker_dy=0, text_dx=0, text_dy=0,
    speaker_box=True, speaker_box_color="#c0392b",
    speaker_font_size=13, text_font_size=13,
    ui_scale=1.0, char_pad_top=0, char_scale=1.0, text_area_w=0,
)

_POS_FRAC = {"L": 0.12, "CL": 0.30, "C": 0.50, "CR": 0.70, "R": 0.88}

# Layout config and asset URLs are read on every uncached render but change only
# when someone edits them, so a short TTL keeps three DB round-trips off the
# hot path without making editor changes feel stuck.
_ASSET_TTL = 60.0
_asset_cache: dict = {}


async def _cached(key, loader):
    import time as _time
    hit = _asset_cache.get(key)
    if hit and _time.monotonic() - hit[0] < _ASSET_TTL:
        return hit[1]
    value = await loader()
    _asset_cache[key] = (_time.monotonic(), value)
    return value


def clear_asset_cache() -> None:
    _asset_cache.clear()


class _NodeWorker:
    """One persistent `node render_node.js` subprocess."""

    def __init__(self) -> None:
        self._proc:  Optional[asyncio.subprocess.Process] = None
        self._lock   = asyncio.Lock()

    async def _ensure(self) -> asyncio.subprocess.Process:
        if self._proc is None or self._proc.returncode is not None:
            self._proc = await asyncio.create_subprocess_exec(
                "node", str(_NODE_SCRIPT),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        return self._proc

    async def render(self, payload: dict) -> bytes:
        async with self._lock:
            proc = await self._ensure()
            line = json.dumps(payload, ensure_ascii=False) + "\n"
            proc.stdin.write(line.encode())
            await proc.stdin.drain()

            # read 4-byte length header
            hdr = await proc.stdout.readexactly(4)
            length = struct.unpack(">I", hdr)[0]
            if length == 0:
                err = await proc.stderr.read(256)
                raise RuntimeError(f"Node render failed: {err.decode(errors='replace')}")
            return await proc.stdout.readexactly(length)

    async def close(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.terminate()
            await self._proc.wait()


class _NodePool:
    def __init__(self, size: int) -> None:
        self._workers: list[_NodeWorker] = [_NodeWorker() for _ in range(size)]
        self._queue:   asyncio.Queue[_NodeWorker] = asyncio.Queue()
        self._started  = False

    async def _start(self) -> None:
        if self._started:
            return
        self._started = True
        for w in self._workers:
            await self._queue.put(w)

    async def render(self, payload: dict) -> bytes:
        await self._start()
        worker = await self._queue.get()
        try:
            return await worker.render(payload)
        except Exception:
            # worker may have crashed — replace it and return the new one to the pool
            new_worker = _NodeWorker()
            self._workers[self._workers.index(worker)] = new_worker
            worker = new_worker
            raise
        finally:
            await self._queue.put(worker)

    async def close(self) -> None:
        for w in self._workers:
            await w.close()


_pool: Optional[_NodePool] = None


def _get_pool() -> _NodePool:
    global _pool
    if _pool is None:
        _pool = _NodePool(_POOL_SIZE)
    return _pool


async def shutdown_pool() -> None:
    global _pool
    if _pool:
        await _pool.close()
        _pool = None


# ── Public entry point ────────────────────────────────────────────────────────

async def render_scene_image(db, story: dict, scene: dict, party_chars: list) -> io.BytesIO:
    """Composite the scene via Node.js and return PNG as a BytesIO."""

    def _resolve(text: str, use_last_name: bool = False) -> str:
        def _name(slot: int) -> str:
            ch = party_chars[slot] if slot < len(party_chars) and party_chars[slot] else None
            if not ch:
                return f"Party Member {slot + 1}"
            name = ch["name"]
            if use_last_name:
                parts = name.strip().split()
                return parts[-1] if len(parts) > 1 else name
            return name
        return re.sub(r'\{party:(\d+)\}', lambda m: _name(int(m.group(1))), text or "")

    async def _load_cfg():
        try:
            return await db.get_vn_config() or {}
        except Exception:
            return {}

    async def _resolve_bg():
        if not scene.get("bg_key"):
            return None
        row = await db.get_vn_background_by_key(scene["bg_key"])
        return row.get("public_url") if row else None

    async def _resolve_ui():
        if not scene.get("ui_asset_id"):
            return None
        row = await db.get_vn_ui_asset(scene["ui_asset_id"])
        return row.get("public_url") if row else None

    cfg_row, bg_url, ui_url = await asyncio.gather(
        _cached("cfg", _load_cfg),
        _cached(f"bg:{scene.get('bg_key')}", _resolve_bg),
        _cached(f"ui:{scene.get('ui_asset_id')}", _resolve_ui),
    )
    cfg = {**_VN_CONFIG_DEFAULTS, **cfg_row}

    # Build character list with resolved URLs (handles party AND story characters)
    chars = []
    for entry in (scene.get("chars") or []):
        ch = None
        if entry.get("type") == "party":
            slot = entry.get("slot", 0)
            ch = party_chars[slot] if slot < len(party_chars) else None
        else:
            cid = entry.get("character_id")
            if cid:
                ch = next((c for c in party_chars if c and c.get("character_id") == cid), None)
                if ch is None:
                    try:
                        ch = await db.get_gacha_character(cid)
                    except Exception:
                        pass
        url = ((ch.get("image_urls") or [None])[0]) if ch else None
        chars.append({"url": url, "position": entry.get("position", "C")})

    raw_speaker = scene.get("speaker") or "narrator"
    multi_party = len(re.findall(r'\{party:\d+\}', raw_speaker)) > 1

    payload = {
        "bg_url":        bg_url,
        "ui_url":        ui_url,
        "chars":         chars,
        "speaker":       _resolve(raw_speaker, use_last_name=multi_party),
        "dialogue_text": _resolve(scene.get("dialogue_text") or ""),
        "text_color":    scene.get("text_color") or "black",
        "ui_scale":      float(scene.get("ui_scale") or cfg.get("ui_scale") or 1.0),
        "bg_blur":       float(scene.get("bg_blur") or 0.0),
        "scene_type":    scene.get("scene_type", "story"),
        "ending_type":   scene.get("ending_type"),
        "choices":       scene.get("choices") or [],
        "cfg":           cfg,
    }

    png_bytes = await _get_pool().render(payload)
    return io.BytesIO(png_bytes)
