"""
Why is the VN showing "Party Member 2" instead of names?

Run on the machine the bot runs on, from the repo root:

    python scripts/vn_editor/diagnose_vn.py <guild_id> <user_id>

Checks, in order: is the deployed code current, what is actually stored as the
party, and do those character ids resolve. Read-only — changes nothing.
"""
import asyncio
import json
import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import asyncpg
from dotenv import load_dotenv

load_dotenv()

COG = ROOT / "cogs" / "gacha" / "vn" / "cog.py"
DBV = ROOT / "database" / "_vn.py"

MARKERS = [
    (COG, "party slots filled before starting", "full-party gate"),
    (COG, "len([c for c in party_ids if c]) < needed", "frozen-party repair"),
    (DBV, "async def set_vn_run_party", "set_vn_run_party"),
    (DBV, "async def get_vn_party_chars", "get_vn_party_chars"),
]


def check_code() -> bool:
    print("── deployed code")
    ok = True
    for path, marker, label in MARKERS:
        try:
            present = marker in path.read_text(encoding="utf-8")
        except OSError as exc:
            print(f"   ?  {label}: cannot read {path} ({exc})")
            ok = False
            continue
        print(f"   {'OK' if present else 'MISSING'}  {label}")
        ok &= present
    if not ok:
        print("\n   This checkout is older than the party fixes. Pull and restart;\n"
              "   nothing below will explain the behaviour until it matches.")
    return ok


async def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    guild_id, user_id = int(sys.argv[1]), int(sys.argv[2])

    code_ok = check_code()

    url = os.getenv("DATABASE_URL") or os.getenv("VN_DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL is not set")
    conn = await asyncpg.connect(url)

    def _party(v):
        return json.loads(v) if isinstance(v, str) else (v or [])

    print("\n── vn_party (what /party saved)")
    row = await conn.fetchrow(
        "SELECT party FROM vn_party WHERE guild_id=$1 AND user_id=$2", guild_id, user_id
    )
    live = _party(row["party"]) if row else []
    print(f"   {live or 'no row — party has never been set'}")

    print("\n── vn_progress (in-flight runs)")
    runs = await conn.fetch(
        "SELECT story_id, scene_id, party, run_active, completed_at FROM vn_progress "
        "WHERE guild_id=$1 AND user_id=$2 ORDER BY updated_at DESC", guild_id, user_id
    )
    if not runs:
        print("   no rows")
    for r in runs:
        frozen = _party(r["party"])
        flag = "ACTIVE" if r["run_active"] else ("done" if r["completed_at"] else "idle")
        print(f"   [{flag:6}] {r['story_id']:28} scene={r['scene_id']:16} party={frozen}")

    print("\n── do those ids resolve to characters?")
    wanted = [c for c in (live + [c for r in runs for c in _party(r['party'])]) if c]
    wanted = list(dict.fromkeys(wanted))
    if not wanted:
        print("   nothing to look up")
    else:
        found = await conn.fetch(
            "SELECT character_id, name, enabled FROM gacha_characters "
            "WHERE character_id = ANY($1)", wanted
        )
        by_id = {r["character_id"]: r for r in found}
        for cid in wanted:
            r = by_id.get(cid)
            print(f"   {'OK     ' if r else 'MISSING'} {cid!r}"
                  + (f"  -> {r['name']} (enabled={r['enabled']})" if r else ""))
        missing = [c for c in wanted if c not in by_id]
        if missing:
            print(f"\n   {len(missing)} id(s) are not in gacha_characters. The party editor\n"
                  "   reads through gacha_claims, so a claim can outlive a deleted or\n"
                  "   renamed character and still show a name in /party.")

    await conn.close()

    print("\n── verdict")
    if not code_ok:
        print("   Stale deploy. Pull the party fixes and restart the gateway.")
    elif row and all(live[:3]) and all(c in by_id for c in live[:3] if c):
        print("   Code and data both look right. If names are still wrong, the scene\n"
              "   was rendered before the restart — press Next once to force a\n"
              "   fresh render, or Play Again to restart the episode.")
    else:
        print("   See the MISSING lines above.")


if __name__ == "__main__":
    asyncio.run(main())
