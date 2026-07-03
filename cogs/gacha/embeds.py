import random

import discord

from .constants import FACTION_COLOR, FACTION_LABEL, RARITY_STARS, DUPE_COLOR

__all__ = [
    "stars",
    "pick_image",
    "roll_embed",
    "claimed_embed",
    "image_embed",
    "harem_image_embed",
    "browse_embed",
]


def stars(rarity: str) -> str:
    n = RARITY_STARS.get(rarity, 1)
    return "★" * n + "☆" * (5 - n)


def pick_image(char: dict) -> str | None:
    urls = char.get("image_urls") or []
    return random.choice(urls) if urls else None


def _suggested_by(char: dict) -> str:
    username = char.get("submitted_by_username")
    return f"  ·  Suggested by @{username}" if username else ""


def roll_embed(
    char: dict,
    image_url: str | None,
    rolls_remaining: int,
    max_rolls: int,
    dupe: bool = False,
    owner_name: str | None = None,
) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    rolls_part = (
        f"⚠️ {rolls_remaining}/{max_rolls} rolls remaining"
        if rolls_remaining <= 2
        else f"{rolls_remaining}/{max_rolls} rolls remaining"
    )
    color = DUPE_COLOR if dupe else FACTION_COLOR.get(char["faction"], 0xCC0000)
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {stars(char['rarity'])}",
        color=color,
    )
    if image_url:
        embed.set_image(url=image_url)
    credit = _suggested_by(char)
    if dupe:
        belongs = f"Belongs to {owner_name}  ·  " if owner_name else ""
        embed.set_footer(text=f"{belongs}{rolls_part}{credit}")
    else:
        embed.set_footer(text=f"React with any emoji to claim!  ·  {rolls_part}{credit}")
    return embed


def claimed_embed(
    char: dict,
    image_url: str | None,
    claimer_name: str,
    rank: int | None = None,
) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    rank_part = f"  ·  Global #{rank}" if rank else ""
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {stars(char['rarity'])}",
        color=0xFF69B4,
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Claimed by {claimer_name}{rank_part}{_suggested_by(char)}")
    return embed


def image_embed(char: dict, url: str, index: int, total: int, rank_text: str) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    page = f"  ·  {index + 1}/{total}" if total > 1 else ""
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {stars(char['rarity'])}",
        color=FACTION_COLOR.get(char["faction"], 0xCC0000),
    )
    embed.set_image(url=url)
    embed.set_footer(text=f"{rank_text}{page}")
    return embed


def harem_image_embed(
    char: dict,
    image_url: str,
    rank_info: dict,
    idx: int,
    total: int,
    owner_name: str,
) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    rank_text = (
        f"Claim Rank: #{rank_info['rank']}  ·  {rank_info['claims']} claims"
        if rank_info.get("rank") else "Unclaimed globally"
    )
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {stars(char['rarity'])}\n{rank_text}",
        color=0xFF69B4,
    )
    embed.set_image(url=image_url)
    embed.set_footer(text=f"Belongs to {owner_name}  ·  {idx + 1}/{total}")
    return embed


def browse_embed(
    page_items: list[tuple[str, dict]],
    page: int,
    total_pages: int,
    faction: str | None,
    rarity: str | None,
    owned: set[str],
) -> discord.Embed:
    filters = []
    if faction:
        filters.append(FACTION_LABEL.get(faction, faction.upper()))
    if rarity:
        filters.append(rarity.upper())
    title = "Waifu Catalogue"
    if filters:
        title += f" · {' · '.join(filters)}"
    lines = [
        f"`{'✓' if cid in owned else '·'}` {stars(ch['rarity'])} **{ch['name']}** — {ch['title']}"
        for cid, ch in page_items
    ]
    embed = discord.Embed(
        title=title,
        description="\n".join(lines) or "No waifus match.",
        color=0xCC0000,
    )
    embed.set_footer(text=f"Page {page + 1}/{total_pages}  ·  ✓ = owned")
    return embed
