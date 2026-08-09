import difflib
import re
import unicodedata

import discord
from discord import app_commands

from . import characters
from .constants import RARITY_EMOJI

# Every query token must clear this against some token of the candidate name.
# Whole-string ratios are not usable here: "gabe newell" vs "alex newell"
# scores 0.82 purely on the shared surname, so the given name gets ignored.
_TOKEN_CUTOFF        = 0.74
_SINGLE_TOKEN_CUTOFF = 0.82
_MIN_PREFIX_LEN      = 2


def _normalize(text: str) -> str:
    """Casefold, strip accents, drop punctuation."""
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return re.sub(r"[^\w\s]", " ", text).strip()


def _tokens(text: str) -> list[str]:
    return _normalize(text).split()


def _token_score(q_token: str, name_tokens: list[str]) -> float:
    best = 0.0
    for nt in name_tokens:
        if len(q_token) >= _MIN_PREFIX_LEN and nt.startswith(q_token):
            return 1.0
        best = max(best, difflib.SequenceMatcher(None, q_token, nt).ratio())
    return best


def _name_score(q_tokens: list[str], name: str) -> float:
    """Mean per-token score, or 0.0 if any single query token fails.

    Requiring *every* token to find a partner is what stops a shared surname
    from carrying an otherwise wrong match.
    """
    name_tokens = _tokens(name)
    if not name_tokens or not q_tokens:
        return 0.0
    cutoff = _SINGLE_TOKEN_CUTOFF if len(q_tokens) == 1 else _TOKEN_CUTOFF
    total  = 0.0
    for qt in q_tokens:
        score = _token_score(qt, name_tokens)
        if score < cutoff:
            return 0.0
        total += score
    return total / len(q_tokens)


def _ranked(query: str) -> list[tuple[float, str, dict]]:
    """Candidates ordered best-first. Empty when nothing is close enough."""
    chars    = characters.all_chars()
    index    = characters.name_index()
    q_raw    = query.lower().strip()
    q_norm   = _normalize(query)
    q_tokens = q_norm.split()

    if q_raw in chars:
        return [(1.0, q_raw, chars[q_raw])]
    if q_raw in index:
        cid = index[q_raw]
        return [(1.0, cid, chars[cid])]

    scored: list[tuple[float, str, dict]] = []
    for cid, ch in chars.items():
        name_norm = _normalize(ch["name"])
        if name_norm == q_norm:
            return [(1.0, cid, ch)]

        if q_norm and q_norm in name_norm:
            # Substring hits rank by how much of the name the query covers, so
            # "newell" prefers "Newell" over "Newellington".
            bonus = 0.90 + 0.09 * (len(q_norm) / max(len(name_norm), 1))
            scored.append((bonus, cid, ch))
            continue

        score = _name_score(q_tokens, ch["name"])
        if score > 0.0:
            scored.append((score * 0.89, cid, ch))

    scored.sort(key=lambda t: (-t[0], len(t[2]["name"])))
    return scored


def find_one(query: str) -> dict | None:
    """Best match for query — returns dict with 'id' key, or None."""
    ranked = _ranked(query)
    if not ranked:
        return None
    _, cid, ch = ranked[0]
    return {"id": cid, **ch}


def find_all(query: str) -> list[dict]:
    """All plausible matches for query — each dict has an 'id' key."""
    ranked = _ranked(query)
    if not ranked:
        return []
    top = ranked[0][0]
    # Keep only candidates in the same quality band as the best one.
    return [{"id": cid, **ch} for score, cid, ch in ranked if score >= top - 0.05]


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


async def target_owned_figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    if not interaction.guild:
        return []
    target = interaction.namespace.user
    if target is None or not hasattr(target, "id"):
        return []
    rows    = await interaction.client.db.get_user_collection(interaction.guild.id, target.id)
    owned   = {r["character_id"] for r in rows}
    chars   = characters.all_chars()
    q       = current.lower()
    results = [
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
