"""
gacha/pipeline.py

Single-character enrichment pipeline used by the web approval flow.
Fetches Wikipedia data, derives stats/faction/rarity, uploads image to R2,
and returns a character dict ready to write to gacha_characters.

The bulk populator (scripts/populate_gacha.py) contains additional discovery
and CLI logic that runs locally only — this module is the deployable subset.
"""
import asyncio
import io
import json
import mimetypes
import os
import random
import re
import time
import unicodedata
import urllib.parse
import urllib.request
from datetime import datetime, timedelta

import aiohttp
from dotenv import load_dotenv
from PIL import Image

load_dotenv()

R2_TOKEN      = os.getenv("R2_TOKEN", "")
R2_ACCOUNT_ID = os.getenv("R2_ACCOUNT_ID", "669887f310b5863b8c09e05b37f15243")
R2_BUCKET     = os.getenv("R2_BUCKET", "social-credit-gacha")
R2_PUBLIC_URL = os.getenv("R2_PUBLIC_URL", "https://pub-ad86c963b8fe456fbeea7b50a4362d70.r2.dev").rstrip("/")

_UA = "SocialCreditBot/2.0 (gacha pipeline)"

_FACTION_KW: dict[str, list[str]] = {
    "reds": [
        "communist", "marxist", "bolshevik", "maoist", "leninist", "stalinist",
        "trotskyist", "socialist", "proletariat", "viet cong", "red army",
        "people's republic", "viet minh", "sandinista", "workers' party",
        "communist party", "left-wing revolutionary",
    ],
    "strongmen": [
        "dictator", "fascist", "authoritarian", "junta", "totalitarian",
        "supreme leader", "el caudillo", "il duce", "strongman",
        "ayatollah", "supreme guide", "theocrat", "military government",
    ],
    "conquerors": [
        "field marshal", "general", "admiral", "marshal of", "commander-in-chief",
        "conqueror", "warlord", "great khan", "caesar", "war leader",
        "crusade", "invasion", "military conquest", "legionary",
    ],
    "icons": [
        "actor", "actress", "singer", "pop star", "rapper", "musician",
        "entertainer", "performer", "model", "supermodel", "influencer",
        "television personality", "tv personality", "talk show host",
        "footballer", "basketball player", "tennis player", "boxer",
        "athlete", "racing driver", "formula one", "nba", "nfl",
        "olympian", "olympic", "golfer", "wrestler", "mma fighter",
        "mixed martial arts", "youtuber", "streamer", "social media",
        "celebrity", "film actor", "television actor", "comedian",
        "stand-up", "reality television", "reality tv",
        "content creator", "podcaster", "tiktoker", "vlogger",
        "esports", "professional gamer", "twitch",
        "k-pop", "idol", "boy band", "girl group",
        "chef", "restaurateur", "food critic", "culinary",
        "fashion designer", "fashion model", "runway model",
        "dancer", "choreographer", "ballet", "gymnast",
        "dj", "disc jockey", "electronic music", "producer",
        "film director", "screenwriter", "cinematographer",
        "drag queen", "drag performer", "cabaret",
        "magician", "illusionist", "circus",
        "voice actor", "narrator", "host",
        "cricket player", "cricketer", "rugby player",
        "swimmer", "cyclist", "sprinter", "marathon runner",
        "figure skater", "skier", "snowboarder",
        "surfer", "skateboarder", "extreme sports",
        "mountaineer", "climber", "adventurer", "daredevil",
        "professional poker player",
    ],
    "capitalists": [
        "president", "prime minister", "chancellor", "senator", "congressman",
        "conservative", "tory", "liberal democrat", "centre-right",
        "businessman", "entrepreneur", "industrialist", "banker",
        "chief executive", "founder", "magnate", "tycoon", "billionaire",
        "venture capitalist", "hedge fund", "private equity",
        "tech entrepreneur", "startup founder", "ceo", "cto", "cfo",
        "real estate developer", "media mogul", "publishing executive",
        "investment banker", "stockbroker", "financier",
        "crypto", "cryptocurrency", "blockchain entrepreneur",
    ],
    "philosophers": [
        "philosopher", "economist", "political theorist", "intellectual",
        "theologian", "scholar", "jurist", "political scientist",
        "political philosopher", "social theorist",
        "linguist", "anthropologist", "sociologist", "psychologist",
        "historian", "classicist", "archaeologist", "literary critic",
        "ethicist", "logician", "metaphysician", "epistemologist",
        "futurist", "transhumanist", "effective altruist",
        "science communicator", "science writer", "public intellectual",
        "professor", "academic", "researcher", "author",
        "journalist", "columnist", "essayist", "critic",
        "lawyer", "attorney", "judge", "legal scholar",
        "doctor", "physician", "scientist", "inventor",
        "architect", "urban planner", "designer",
    ],
}

_RARITY: list[tuple[int, str]] = [
    (2_000_000, "legendary"),
    (500_000,   "epic"),
    (80_000,    "rare"),
    (15_000,    "uncommon"),
    (0,         "common"),
]

_STATS: dict[str, dict[str, tuple[int, int]]] = {
    "reds":        {"authority": (68, 96), "military": (38, 82), "charisma": (58, 92)},
    "capitalists": {"authority": (68, 92), "military": (28, 68), "charisma": (58, 95)},
    "conquerors":  {"authority": (68, 98), "military": (80, 100), "charisma": (48, 86)},
    "strongmen":   {"authority": (78, 96), "military": (48, 86), "charisma": (32, 78)},
    "philosophers":{"authority": (22, 62), "military": (4, 28),  "charisma": (58, 92)},
    "icons":       {"authority": (18, 55), "military": (2, 18),  "charisma": (72, 99)},
    "wildcards":   {"authority": (28, 80), "military": (4, 62),  "charisma": (58, 98)},
}

_NOT_PERSON_RE = re.compile(
    r"fictional|\bfictitious\b"
    r"|television (series|show|episode|program)"
    r"|\btv (series|show|episode)\b"
    r"|\banimated (series|film|show)\b"
    r"|\bshort story\b|\bvideo game\b|\bcomic (book|strip)\b|\bgraphic novel\b"
    r"|\bpolitical party\b|\btrade union\b|\bnewspaper\b|\bperiodical\b"
    r"|\bspacecraft\b|\bsatellite\b|\bspace station\b"
    r"|\bhurricane\b|\bcyclone\b|\btyphoon\b|\basteroid\b|\bcomet\b"
    r"|\brecord label\b|\bmonument\b|\bstadium\b"
    r"|\bnovels?\s+(by|series\b)"
    r"|\b(series|collection) of novels\b"
    r"|\d{3,4}\s*[–\-]\s*\d{2,4}\s+series\b"
    r"|\bseries by\b"
    r"|\bepisode of\b|\bseason of\b",
    re.IGNORECASE,
)

_PERSON_DESC_RE = re.compile(
    r"\b("
    r"politician|statesman|president|prime minister|chancellor|"
    r"emperor|empress|king|queen|prince|princess|tsar|sultan|caliph|pharaoh|"
    r"general|admiral|marshal|commander|warlord|"
    r"revolutionary|activist|dictator|secretary.general|"
    r"philosopher|economist|theorist|scholar|jurist|"
    r"businessman|entrepreneur|religious leader|pope|cardinal|imam|"
    r"explorer|conquistador|spy|diplomat|"
    r"physicist|chemist|biologist|mathematician|astronomer|"
    r"engineer|inventor|scientist|"
    r"composer|musician|pianist|violinist|guitarist|drummer|"
    r"singer|conductor|rapper|producer|songwriter|"
    r"painter|sculptor|artist|photographer|architect|"
    r"writer|novelist|poet|playwright|journalist|author|essayist|"
    r"director|actor|actress|comedian|filmmaker|"
    r"boxer|footballer|athlete|chess player|racing driver|"
    r"banker|financier|magnate|tycoon|investor|"
    r"astronaut|aviator|mountaineer|oceanographer"
    r")\b",
    re.IGNORECASE,
)

_BORN_RE = re.compile(r"\b(born|died)\b|\b\d{3,4}\s*[–\-]\s*\d{2,4}\b", re.IGNORECASE)

_GENDER_QID: dict[str, str] = {
    "Q6581097": "male",
    "Q6581072": "female",
    "Q2449503": "female",
    "Q2449532": "male",
    "Q1097630": "other",
    "Q48270":   "other",
    "Q505371":  "other",
}

_HE_RE  = re.compile(r"\b(he|his|him)\b", re.IGNORECASE)
_SHE_RE = re.compile(r"\b(she|her|hers)\b", re.IGNORECASE)

_IMG_EXT  = re.compile(r"\.(jpe?g|png|webp)$", re.IGNORECASE)
_IMG_SKIP = re.compile(
    r"(signature|logo|coat.of.arms|flag|map|symbol|seal|emblem|icon|commons-logo)",
    re.IGNORECASE,
)


def _sync_get(url: str, headers: dict | None = None) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=14) as r:
            return r.read()
    except Exception:
        return None


async def _aget(url: str, sem: asyncio.Semaphore, headers: dict | None = None) -> bytes | None:
    async with sem:
        return await asyncio.to_thread(_sync_get, url, headers)


def _is_person_summary(d: dict) -> bool:
    desc = (d.get("description") or "").strip()
    if _NOT_PERSON_RE.search(desc):
        return False
    return bool(_PERSON_DESC_RE.search(desc)) or bool(_BORN_RE.search(desc))


def _gender_from_pronouns(extract: str) -> str | None:
    he  = len(_HE_RE.findall(extract[:500]))
    she = len(_SHE_RE.findall(extract[:500]))
    if he == 0 and she == 0:
        return None
    return "female" if she > he else ("male" if he > she else None)


def _sync_wiki_gender(slug: str, lang: str = "en") -> str | None:
    req = urllib.request.Request(
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageprops&ppprop=wikibase_item&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            combo = json.loads(r.read())
    except Exception:
        return None
    qid = None
    for page in combo.get("query", {}).get("pages", {}).values():
        qid = page.get("pageprops", {}).get("wikibase_item")
    if not qid:
        return None
    time.sleep(0.15)
    req2 = urllib.request.Request(
        f"https://www.wikidata.org/w/api.php?action=wbgetclaims"
        f"&entity={qid}&property=P21&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req2, timeout=10) as r:
            wd = json.loads(r.read())
    except Exception:
        return None
    for claim in wd.get("claims", {}).get("P21", []):
        gid = claim.get("mainsnak", {}).get("datavalue", {}).get("value", {}).get("id", "")
        if gid in _GENDER_QID:
            return _GENDER_QID[gid]
    return None


async def wiki_gender(slug: str, sem: asyncio.Semaphore, extract: str = "", lang: str = "en") -> str | None:
    async with sem:
        result = await asyncio.to_thread(_sync_wiki_gender, slug, lang)
    return result or _gender_from_pronouns(extract)


async def wiki_summary(slug: str, sem: asyncio.Semaphore, lang: str = "en") -> dict | None:
    url = f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(slug)}"
    raw = await _aget(url, sem)
    if not raw:
        return None
    try:
        d = json.loads(raw)
        return {"description": d.get("description", ""), "extract": d.get("extract", "")}
    except Exception:
        return None


async def wiki_views(slug: str, sem: asyncio.Semaphore, lang: str = "en") -> int:
    now   = datetime.utcnow()
    start = (now - timedelta(days=180)).strftime("%Y%m%d")
    end   = now.strftime("%Y%m%d")
    url = (
        "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
        f"/{lang}.wikipedia/all-access/all-agents/{urllib.parse.quote(slug)}/monthly/{start}/{end}"
    )
    raw = await _aget(url, sem)
    if not raw:
        return 0
    try:
        items = json.loads(raw).get("items", [])
        return sum(i.get("views", 0) for i in items) // len(items) if items else 0
    except Exception:
        return 0


def _resolve_file_url(fname: str) -> str | None:
    url = (
        "https://commons.wikimedia.org/w/api.php"
        f"?action=query&titles=File:{urllib.parse.quote(fname.replace(' ', '_'), safe='')}"
        "&prop=imageinfo&iiprop=url&iiurlwidth=800&format=json"
    )
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                pages = json.loads(r.read()).get("query", {}).get("pages", {})
            for page in pages.values():
                for ii in page.get("imageinfo", []):
                    return ii.get("thumburl") or ii.get("url") or None
            return None
        except Exception as e:
            if "429" in str(e) and attempt < 2:
                time.sleep(3 + attempt * 2)
            else:
                return None
    return None


def _sync_wiki_infobox_img(slug: str, lang: str = "en") -> list[str]:
    req = urllib.request.Request(
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageimages&piprop=thumbnail&pithumbsize=800&format=json",
        headers={"User-Agent": _UA},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read())
        for page in data.get("query", {}).get("pages", {}).values():
            src = page.get("thumbnail", {}).get("source", "")
            if src and _IMG_EXT.search(src) and not _IMG_SKIP.search(src):
                return [src]
    except Exception:
        pass
    return []


def _sync_wiki_imgs(slug: str, max_images: int = 5, lang: str = "en") -> list[str]:
    results: list[str] = []
    seen: set[str] = set()

    def _add(url: str) -> bool:
        if url and url not in seen:
            seen.add(url)
            results.append(url)
            return True
        return False

    def _get(url: str, timeout: int = 12) -> dict:
        for attempt in range(3):
            req = urllib.request.Request(url, headers={"User-Agent": _UA})
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r:
                    return json.loads(r.read())
            except Exception as e:
                if "429" in str(e) and attempt < 2:
                    time.sleep(3 + attempt * 3)
                else:
                    return {}
        return {}

    combo = _get(
        f"https://{lang}.wikipedia.org/w/api.php"
        f"?action=query&titles={urllib.parse.quote(slug, safe='')}"
        "&prop=pageimages|pageprops&piprop=thumbnail&pithumbsize=800"
        "&ppprop=wikibase_item&format=json"
    )
    qid: str | None = None
    for page in combo.get("query", {}).get("pages", {}).values():
        src = page.get("thumbnail", {}).get("source", "")
        if src and _IMG_EXT.search(src) and not _IMG_SKIP.search(src):
            _add(src)
        qid = page.get("pageprops", {}).get("wikibase_item")

    if not results or not qid:
        rest = _get(f"https://{lang}.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(slug, safe='')}")
        orig = rest.get("originalimage", {}).get("source", "") or rest.get("thumbnail", {}).get("source", "")
        if orig and _IMG_EXT.search(orig) and not _IMG_SKIP.search(orig):
            _add(orig)
        if not qid:
            sq = urllib.parse.quote(rest.get("title", slug.replace("_", " ")))
            wd_search = _get(
                f"https://www.wikidata.org/w/api.php?action=wbsearchentities"
                f"&search={sq}&language=en&limit=1&format=json"
            )
            hits = wd_search.get("search", [])
            if hits:
                qid = hits[0].get("id")

    if len(results) >= max_images or not qid:
        return results

    time.sleep(0.5)

    wd_data = _get(
        f"https://www.wikidata.org/w/api.php?action=wbgetclaims"
        f"&entity={qid}&property=P18&format=json"
    )
    for claim in wd_data.get("claims", {}).get("P18", []):
        if len(results) >= max_images:
            break
        fname = claim.get("mainsnak", {}).get("datavalue", {}).get("value", "")
        if fname and _IMG_EXT.search(fname) and not _IMG_SKIP.search(fname):
            time.sleep(0.3)
            src = _resolve_file_url(fname)
            if src:
                _add(src)

    if len(results) >= max_images:
        return results

    time.sleep(0.5)

    search_q = urllib.parse.quote(f"haswbstatement:P180={qid}", safe=":")
    ms_data = _get(
        f"https://commons.wikimedia.org/w/api.php"
        f"?action=query&list=search&srnamespace=6"
        f"&srsearch={search_q}&srlimit=20&format=json"
    )
    hits = ms_data.get("query", {}).get("search", [])
    _PREFER = re.compile(r"(crop|portrait|official|headshot)", re.IGNORECASE)
    hits.sort(key=lambda h: (0 if _PREFER.search(h.get("title", "")) else 1))
    for hit in hits:
        if len(results) >= max_images:
            break
        fname = hit.get("title", "").replace("File:", "")
        if not (_IMG_EXT.search(fname) and not _IMG_SKIP.search(fname)):
            continue
        time.sleep(0.2)
        src = _resolve_file_url(fname)
        if src:
            _add(src)

    return results[:max_images]


async def wiki_images(slug: str, sem: asyncio.Semaphore, max_images: int = 5, lang: str = "en") -> list[str]:
    async with sem:
        return await asyncio.to_thread(_sync_wiki_imgs, slug, max_images, lang)


_GACHA_W = 225
_GACHA_H = 350


def _normalize_image(data: bytes) -> bytes:
    """Center-crop to 9:14 portrait, resize to 225×350, encode as PNG."""
    img   = Image.open(io.BytesIO(data)).convert("RGB")
    w, h  = img.size
    ratio = _GACHA_W / _GACHA_H
    if w / h > ratio:
        new_w = int(h * ratio)
        img   = img.crop(((w - new_w) // 2, 0, (w - new_w) // 2 + new_w, h))
    elif w / h < ratio:
        new_h = int(w / ratio)
        img   = img.crop((0, 0, w, new_h))
    img = img.resize((_GACHA_W, _GACHA_H), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def _sync_dl(url: str) -> tuple[bytes | None, str]:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.read(), r.headers.get_content_type() or "image/jpeg"
    except Exception:
        return None, "image/jpeg"


async def upload_r2(
    session: aiohttp.ClientSession,
    char_id: str,
    img_url: str,
    index: int,
    sem: asyncio.Semaphore,
) -> str | None:
    img_data, _ = await asyncio.to_thread(_sync_dl, img_url)
    if not img_data:
        return None
    try:
        img_data = await asyncio.to_thread(_normalize_image, img_data)
    except Exception:
        return None
    key = f"gacha/{char_id}/{index}.png"
    api = (
        f"https://api.cloudflare.com/client/v4/accounts/{R2_ACCOUNT_ID}"
        f"/r2/buckets/{R2_BUCKET}/objects/{key}"
    )
    async with sem:
        try:
            async with session.put(
                api, data=img_data,
                headers={"Authorization": f"Bearer {R2_TOKEN}", "Content-Type": "image/png"},
                timeout=aiohttp.ClientTimeout(total=30),
            ) as r:
                if r.status in (200, 201):
                    return f"{R2_PUBLIC_URL}/{key}"
        except Exception:
            pass
    return None


async def upload_r2_multi(
    session: aiohttp.ClientSession,
    char_id: str,
    img_urls: list[str],
    sem: asyncio.Semaphore,
) -> list[str]:
    tasks = [upload_r2(session, char_id, url, i + 1, sem) for i, url in enumerate(img_urls)]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r]


def derive_faction(description: str, extract: str) -> str:
    text = (description + " " + extract[:400]).lower()
    scores = {f: sum(1 for kw in kws if kw in text) for f, kws in _FACTION_KW.items()}
    best = max(scores, key=lambda f: scores[f])
    return best if scores[best] > 0 else "wildcards"


def derive_rarity(monthly_views: int) -> str:
    for threshold, rarity in _RARITY:
        if monthly_views >= threshold:
            return rarity
    return "common"


def derive_stats(faction: str, sitelinks: int) -> dict:
    fame = min(sitelinks // 8, 12)
    return {
        stat: min(100, random.randint(lo, hi) + fame)
        for stat, (lo, hi) in _STATS.get(faction, _STATS["wildcards"]).items()
    }


def derive_title(description: str, name: str) -> str:
    t = (description or name).strip()
    return t[:65].rsplit(" ", 1)[0] + "..." if len(t) > 68 else t


def make_char_id(name: str, taken: set[str]) -> str:
    n = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    base = re.sub(r"\s+", "_", re.sub(r"[^a-z0-9\s]", "", n.lower()).strip())
    cid, i = base, 2
    while cid in taken:
        cid, i = f"{base}_{i}", i + 1
    return cid


async def process_one(
    item: dict,
    r2_session: aiohttp.ClientSession,
    wiki_sem: asyncio.Semaphore,
    r2_sem: asyncio.Semaphore,
    dry_run: bool = False,
    override_image_urls: list[str] | None = None,
    fast: bool = False,
    lang: str = "en",
) -> tuple[str, dict] | None:
    slug = item["slug"]
    name = item["name"]

    if fast:
        summary_t = wiki_summary(slug, wiki_sem, lang)
        images_t  = asyncio.sleep(0, result=[]) if override_image_urls else asyncio.to_thread(_sync_wiki_infobox_img, slug, lang)
        summary, img_urls = await asyncio.gather(summary_t, images_t)
        if not summary or not _is_person_summary(summary):
            return None
        monthly_views = item.get("langlinks", 30) * 5000
        gender = _gender_from_pronouns(summary.get("extract", ""))
    else:
        summary_t = wiki_summary(slug, wiki_sem, lang)
        views_t   = wiki_views(slug, wiki_sem, lang)
        images_t  = asyncio.sleep(0, result=[]) if override_image_urls else wiki_images(slug, wiki_sem, max_images=5, lang=lang)
        gender_t  = wiki_gender(slug, wiki_sem, lang=lang)
        summary, monthly_views, img_urls, gender = await asyncio.gather(summary_t, views_t, images_t, gender_t)
        if not summary or not _is_person_summary(summary):
            return None
        if not gender:
            gender = _gender_from_pronouns(summary.get("extract", ""))

    faction = derive_faction(summary["description"], summary["extract"])
    rarity  = derive_rarity(monthly_views)
    stats   = derive_stats(faction, item.get("sitelinks", 30))
    title   = derive_title(summary["description"], name)

    if override_image_urls:
        img_urls = override_image_urls

    public_urls: list[str] = []
    if img_urls and not dry_run:
        char_id_tmp = make_char_id(name, set())
        public_urls = await upload_r2_multi(r2_session, char_id_tmp, img_urls, r2_sem)

    if not public_urls and img_urls and not dry_run:
        return None

    return name, {
        "name":       name,
        "title":      title,
        "faction":    faction,
        "rarity":     rarity,
        "quote":      "",
        "stats":      stats,
        "wiki":       slug,
        "gender":     gender,
        "image_urls": public_urls if public_urls else (img_urls[:1] if dry_run else []),
    }


async def process_slug(wiki_slug: str, lang: str = "en") -> dict | None:
    """Single-slug entry point for the web approval pipeline."""
    item = {
        "slug":      wiki_slug,
        "name":      wiki_slug.replace("_", " "),
        "sitelinks": 30,
        "langlinks": 30,
    }
    wiki_sem = asyncio.Semaphore(2)
    r2_sem   = asyncio.Semaphore(2)
    async with aiohttp.ClientSession() as r2_session:
        result = await process_one(item, r2_session, wiki_sem, r2_sem, dry_run=False, lang=lang)
    if result is None:
        return None
    _, char_data = result
    return char_data
