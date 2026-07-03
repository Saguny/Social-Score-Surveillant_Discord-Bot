import difflib

import discord
from discord import app_commands

from . import characters
from .constants import RARITY_EMOJI


def find_one(query: str) -> dict | None:
    """First match for query — returns dict with 'id' key, or None."""
    q     = query.lower().strip()
    chars = characters.all_chars()
    index = characters.name_index()

    if q in chars:
        return {"id": q, **chars[q]}
    if q in index:
        cid = index[q]
        return {"id": cid, **chars[cid]}
    for cid, ch in chars.items():
        if q in ch["name"].lower():
            return {"id": cid, **ch}
    return _fuzzy_match(q)


def find_all(query: str) -> list[dict]:
    """All matches for query — each dict has an 'id' key."""
    q     = query.lower().strip()
    chars = characters.all_chars()

    exact = [{"id": cid, **ch} for cid, ch in chars.items() if ch["name"].lower() == q]
    if exact:
        return exact
    substr = [{"id": cid, **ch} for cid, ch in chars.items() if q in ch["name"].lower()]
    if substr:
        return substr
    match = _fuzzy_match(q)
    return [match] if match else []


def _fuzzy_match(query: str) -> dict | None:
    chars   = characters.all_chars()
    index   = characters.name_index()
    matches = difflib.get_close_matches(query, list(index.keys()), n=1, cutoff=0.70)
    if matches:
        cid = index[matches[0]]
        return {"id": cid, **chars[cid]}
    q_words = set(query.split())
    best, best_score = None, 0
    for cid, ch in chars.items():
        name_words = set(ch["name"].lower().split())
        score = len(q_words & name_words)
        if score > best_score and score >= len(q_words) * 0.6:
            best, best_score = {"id": cid, **ch}, score
    return best


async def figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    q       = current.lower()
    chars   = characters.all_chars()
    results = [(cid, ch) for cid, ch in chars.items() if q in ch["name"].lower() or q in cid]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}", value=cid)
        for cid, ch in results[:25]
    ]


async def owned_figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    rows     = await interaction.client.db.get_user_collection(interaction.guild.id, interaction.user.id)
    owned    = {r["character_id"] for r in rows}
    chars    = characters.all_chars()
    q        = current.lower()
    results  = [
        (cid, chars[cid]) for cid in owned
        if cid in chars and (q in chars[cid]["name"].lower() or q in cid)
    ]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}", value=cid)
        for cid, ch in results[:25]
    ]


async def wishlist_figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    ids    = await interaction.client.db.get_wishlist(interaction.guild.id, interaction.user.id)
    chars  = characters.all_chars()
    q      = current.lower()
    results = [
        (cid, chars[cid]) for cid in ids
        if cid in chars and (q in chars[cid]["name"].lower() or q in cid)
    ]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}", value=cid)
        for cid, ch in results[:25]
    ]
