"""
Retune choice difficulties for the corrected stat modifier.

Existing DCs were authored while the roll modifier was silently always 0, so
every choice has effectively been a bare d20 against its DC. Now that stats
apply, an average party adds +5 and a strong party with both bonuses adds up
to +14 — so those DCs read far easier than they play-tested.

    python scripts/vn_editor/rebalance_dcs.py                 # report only
    python scripts/vn_editor/rebalance_dcs.py --shift 5       # preview a shift
    python scripts/vn_editor/rebalance_dcs.py --shift 5 --apply

Reports first, always. Nothing is written without --apply.
"""
import argparse
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

import asyncio

from dotenv import load_dotenv

load_dotenv()

from scripts.vn_editor.db import close_pool, get_pool

DC_MIN, DC_MAX = 1, 30

AVG_MOD    = 5    # party of three average 50-stat characters
STRONG_MOD = 8
BONUS_MOD  = 14   # strong party, featured character and faction both matching


def _odds(dc: int, mod: int) -> int:
    return round(max(0, min(21 - dc + mod, 20)) / 20 * 100)


def _tier(dc: int) -> str:
    for name, threshold in (("trivial", 9), ("easy", 12), ("medium", 16), ("hard", 20)):
        if dc < threshold:
            return name
    return "brutal"


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shift", type=int, default=0,
                    help="add this to every DC (clamped to 1-30)")
    ap.add_argument("--apply", action="store_true",
                    help="actually write the change")
    args = ap.parse_args()

    pool = await get_pool()
    rows = await pool.fetch(
        "SELECT story_id, id, label, choices FROM vn_scenes "
        "WHERE scene_type = 'choice' ORDER BY story_id, id"
    )

    total = changed = 0
    updates: list[tuple] = []

    print(f"{'story / scene':38} {'choice':28} {'DC':>3} {'tier':8} "
          f"{'avg':>5} {'strong':>7} {'+bonus':>7}")
    print("-" * 104)

    for row in rows:
        choices = row["choices"]
        if isinstance(choices, str):
            choices = json.loads(choices)
        choices = choices or []

        new_choices = []
        touched = False
        for choice in choices:
            dc = int(choice.get("difficulty") or 14)
            total += 1
            new_dc = max(DC_MIN, min(dc + args.shift, DC_MAX)) if args.shift else dc
            if new_dc != dc:
                touched = True
                changed += 1

            shown = new_dc
            arrow = f"{dc}->{shown}" if new_dc != dc else str(dc)
            print(f"{row['story_id'] + ' / ' + row['id']:38.38} "
                  f"{(choice.get('text') or '(untitled)'):28.28} "
                  f"{arrow:>3} {_tier(shown):8} "
                  f"{_odds(shown, AVG_MOD):4}% {_odds(shown, STRONG_MOD):6}% "
                  f"{_odds(shown, BONUS_MOD):6}%")

            updated = dict(choice)
            updated["difficulty"] = new_dc
            new_choices.append(updated)

        if touched:
            updates.append((json.dumps(new_choices), row["id"], row["story_id"]))

    print("-" * 104)
    print(f"{total} choices across {len(rows)} choice scenes")

    if not args.shift:
        print("\nNo --shift given, so nothing would change. Odds above are what "
              "these DCs play like now that stats apply.")
    elif not args.apply:
        print(f"\n{changed} would change by {args.shift:+d}. Re-run with --apply to write.")
    elif updates:
        async with pool.acquire() as conn:
            async with conn.transaction():
                await conn.executemany(
                    "UPDATE vn_scenes SET choices = $1::jsonb WHERE id = $2 AND story_id = $3",
                    updates,
                )
        print(f"\nUpdated {changed} choices across {len(updates)} scenes.")
    else:
        print("\nNothing to write.")

    await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
