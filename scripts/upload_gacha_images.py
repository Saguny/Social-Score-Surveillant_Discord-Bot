"""
Upload gacha character images to Cloudflare R2.

Usage:
    python scripts/upload_gacha_images.py

Env vars required:
    R2_TOKEN        — Cloudflare API token (Workers R2 Storage Read+Edit)
    R2_ACCOUNT_ID   — Cloudflare account ID
    R2_BUCKET       — bucket name (default: social-credit-gacha)
    R2_PUBLIC_URL   — public bucket URL (default: https://pub-ad86c963b8fe456fbeea7b50a4362d70.r2.dev)

Each character in PERSONALITIES gets its Wikipedia main image downloaded and uploaded to:
    gacha/{char_id}/1.jpg  (or .png)

After running, copy the printed image_urls lines into config/personalities.py.
To add more images per character later, upload manually to gacha/{char_id}/2.jpg etc.
and append the URL to the character's image_urls list.
"""
import asyncio
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

import aiohttp
from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from config.personalities import PERSONALITIES

R2_TOKEN      = os.getenv("R2_TOKEN", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "669887f310b5863b8c09e05b37f15243")
R2_BUCKET     = os.getenv("R2_BUCKET", "social-credit-gacha")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "https://pub-ad86c963b8fe456fbeea7b50a4362d70.r2.dev").rstrip("/")

_WIKI_UA = "SocialCreditBot/2.0 (shiroyeshimura@gmail.com; gacha image uploader; https://top.gg/bot/856163780265902151)"


def _sync_get_wiki_image(wiki_slug: str) -> str | None:
    """Wikipedia Action API fetch via urllib (aiohttp gets 403 from Wikipedia)."""
    url = (
        "https://en.wikipedia.org/w/api.php"
        "?action=query"
        f"&titles={urllib.parse.quote(wiki_slug, safe='')}"
        "&prop=pageimages"
        "&piprop=thumbnail"
        "&pithumbsize=800"
        "&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        pages = data.get("query", {}).get("pages", {})
        for page in pages.values():
            thumb = page.get("thumbnail", {}).get("source")
            if thumb:
                return thumb
    except Exception as e:
        print(f"  wiki error: {e}", end=" ")
    return None


async def get_wiki_image(wiki_slug: str) -> str | None:
    return await asyncio.to_thread(_sync_get_wiki_image, wiki_slug)


def _sync_download(url: str) -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": _WIKI_UA})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ct = resp.headers.get_content_type() or "image/jpeg"
            return resp.read(), ct
    except Exception as e:
        print(f"  download error: {e}", end=" ")
        return None, "image/jpeg"


async def download(url: str) -> tuple[bytes | None, str]:
    return await asyncio.to_thread(_sync_download, url)


async def upload_r2(session: aiohttp.ClientSession, key: str, data: bytes, content_type: str) -> bool:
    url = f"https://api.cloudflare.com/client/v4/accounts/{R2_ACCOUNT_ID}/r2/buckets/{R2_BUCKET}/objects/{key}"
    headers = {
        "Authorization": f"Bearer {R2_TOKEN}",
        "Content-Type": content_type,
    }
    try:
        async with session.put(url, data=data, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as r:
            if r.status not in (200, 201):
                body = await r.text()
                print(f"  upload error {r.status}: {body[:120]}")
                return False
            return True
    except Exception as e:
        print(f"  upload error: {e}")
        return False


def ext_from_ct(content_type: str, url: str) -> str:
    ext = mimetypes.guess_extension(content_type)
    if ext in (".jpe", ".jpeg"):
        ext = ".jpg"
    if not ext:
        for candidate in (".jpg", ".png", ".webp"):
            if candidate in url.lower():
                return candidate
        ext = ".jpg"
    return ext


async def main():
    if not R2_TOKEN:
        print("ERROR: R2_TOKEN not set. Add it to your .env file.")
        sys.exit(1)

    results: dict[str, list[str]] = {}
    skipped: list[str] = []

    async with aiohttp.ClientSession() as session:
        for char_id, char in PERSONALITIES.items():
            wiki_slug = char.get("wiki")
            name = char["name"]

            if not wiki_slug:
                print(f"SKIP  {name} — no wiki slug")
                skipped.append(char_id)
                continue

            print(f"      {name} ...", end=" ", flush=True)

            img_url = await get_wiki_image(wiki_slug)
            if not img_url:
                print("no image")
                skipped.append(char_id)
                continue

            img_data, content_type = await download(img_url)
            if not img_data:
                print("download failed")
                skipped.append(char_id)
                continue

            ext = ext_from_ct(content_type, img_url)
            key = f"gacha/{char_id}/1{ext}"

            ok = await upload_r2(session, key, img_data, content_type)
            if ok:
                public_url = f"{R2_PUBLIC_URL}/{key}"
                results[char_id] = [public_url]
                print(f"OK  ({len(img_data) // 1024}KB)")
            else:
                skipped.append(char_id)

            await asyncio.sleep(0.4)

    print(f"\n\n{'─' * 60}")
    print(f"Uploaded: {len(results)}  Skipped: {len(skipped)}")
    if skipped:
        print(f"Skipped IDs: {', '.join(skipped)}")

    print("\n\n# ── Copy these image_urls into config/personalities.py ─────\n")
    for char_id, urls in results.items():
        name = PERSONALITIES[char_id]["name"]
        print(f'    # {name}')
        print(f'    "{char_id}": {{  # add/replace image_urls')
        for u in urls:
            print(f'        "image_urls": ["{u}"],')
        print()


if __name__ == "__main__":
    asyncio.run(main())
