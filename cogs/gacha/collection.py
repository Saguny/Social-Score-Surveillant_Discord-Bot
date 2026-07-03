import asyncio

import discord

from . import characters
from .constants import RARITY_ORDER, RARITY_EMOJI, SUBMIT_URL
from .embeds import stars, pick_image
from .search import find_all
from .views import BrowseView, HaremView, HaremImageView, show_char_picker


def filtered_chars(faction: str | None = None, rarity: str | None = None) -> list[tuple[str, dict]]:
    items = list(characters.all_chars().items())
    if faction:
        items = [(k, v) for k, v in items if v["faction"] == faction]
    if rarity:
        items = [(k, v) for k, v in items if v["rarity"] == rarity]
    items.sort(key=lambda x: (RARITY_ORDER.index(x[1]["rarity"]), x[1]["name"]))
    return items


async def show_top(send_fn, db) -> None:
    rows = await db.get_top_characters(10)
    if not rows:
        await send_fn("No waifus have been claimed yet.")
        return
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines  = []
    for row in rows:
        char = characters.get(row["character_id"])
        if not char:
            continue
        pos    = row["rank"]
        prefix = medals.get(pos) or f"`#{pos}`"
        emoji  = RARITY_EMOJI.get(char["rarity"], "⚪")
        lines.append(f"{prefix} {emoji} **{char['name']}** · {row['claim_count']} claims")
    embed = discord.Embed(
        title="🏆 Most Claimed · Global Top 10",
        description="\n".join(lines) or "None yet.",
        color=0xCC0000,
    )
    await send_fn(embed=embed)


async def show_collection(
    guild_id: int, user: discord.Member | discord.User, send_fn, db, bot
) -> None:
    rows = await db.get_user_collection(guild_id, user.id)
    name = user.display_name if hasattr(user, "display_name") else str(user)
    if not rows:
        await send_fn(f"**{name}** has no waifus yet. Use `/roll` to start collecting!")
        return

    chosen_id  = await db.get_harem_thumbnail(guild_id, user.id)
    thumb_char = characters.get(chosen_id) if chosen_id else None
    if not thumb_char:
        for row in rows:
            c = characters.get(row["character_id"])
            if c and c.get("image_urls"):
                thumb_char = c
                break

    thumb_url = pick_image(thumb_char) if thumb_char else None
    icon_url  = user.display_avatar.url if hasattr(user, "display_avatar") else None

    entries = [
        (row["character_id"], characters.get(row["character_id"]))
        for row in rows
        if characters.get(row["character_id"])
    ]
    entries.sort(key=lambda x: (RARITY_ORDER.index(x[1].get("rarity", "common")), x[1]["name"]))

    if not entries:
        await send_fn(f"**{name}** has no waifus yet. Use `/roll` to start collecting!")
        return

    view = HaremView(entries, name, thumb_url, icon_url, len(entries))
    await send_fn(embed=view.build_embed(), view=view)


async def do_harem_image(
    guild_id: int, user: discord.Member | discord.User, send_fn, db, bot
) -> None:
    rows       = await db.get_user_collection(guild_id, user.id)
    plain_name = user.display_name if hasattr(user, "display_name") else str(user)
    if not rows:
        await send_fn(f"**{plain_name}** has no waifus yet. Use `/roll` to start collecting!")
        return

    entries = [
        (row["character_id"], characters.get(row["character_id"]))
        for row in rows
        if characters.get(row["character_id"]) and characters.get(row["character_id"]).get("image_urls")
    ]
    entries.sort(key=lambda x: (RARITY_ORDER.index(x[1].get("rarity", "common")), x[1]["name"]))

    if not entries:
        await send_fn(f"**{plain_name}** has no waifus with images.")
        return

    char_ids = [e[0] for e in entries]
    ranks, formatted_name = await asyncio.gather(
        db.get_characters_rank_batch(char_ids),
        bot.format_user_full(user, guild_id),
    )

    view_entries = [
        (cid, char, pick_image(char), ranks.get(cid, {"rank": None, "claims": 0}))
        for cid, char in entries
    ]
    view = HaremImageView(view_entries, user.id, formatted_name)
    await send_fn(embed=view.build_embed(), view=view)


async def do_choose(
    guild_id: int, user: discord.Member | discord.User, name: str, send_fn, db
) -> None:
    char = characters.get(name)
    if not char:
        candidates = find_all(name)
        if not candidates:
            await send_fn(f"No waifu found matching **{name}**. Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return
        if len(candidates) > 1:
            await show_char_picker(
                send_fn, candidates, user.id,
                lambda c: do_choose(guild_id, user, c["id"], send_fn, db),
            )
            return
        char = candidates[0]
    char_id = char.get("id", name)
    if not await db.has_character(guild_id, user.id, char_id):
        await send_fn(f"**{char['name']}** is not in your harem.")
        return
    await db.set_harem_thumbnail(guild_id, user.id, char_id)
    await send_fn(f"**{char['name']}** is now your featured waifu.")
