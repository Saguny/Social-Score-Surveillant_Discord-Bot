import asyncio
import io
import json
import random
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config.personalities import RARITY_WEIGHT
from cogs.achievements import unlock as unlock_achievement, check_milestone
from infra.redis_client import get_redis

# Character pool — loaded from DB at cog startup, stays in memory for fast rolls.
_CHARS: dict[str, dict] = {}


def _get_personality(char_id: str) -> dict | None:
    return _CHARS.get(char_id)


def _search_personality(query: str) -> dict | None:
    """Find by name (exact first, then substring). Returns dict with 'id' injected."""
    q = query.lower().strip()
    if q in _CHARS:
        return {"id": q, **_CHARS[q]}
    for cid, ch in _CHARS.items():
        if ch["name"].lower() == q:
            return {"id": cid, **ch}
    for cid, ch in _CHARS.items():
        if q in ch["name"].lower():
            return {"id": cid, **ch}
    return None


def _roll_weighted() -> tuple[str, dict]:
    keys    = list(_CHARS.keys())
    weights = [RARITY_WEIGHT.get(_CHARS[k]["rarity"], 60) for k in keys]
    cid     = random.choices(keys, weights=weights)[0]
    return cid, _CHARS[cid]

CLAIM_WINDOW     = 60
ROLL_WINDOW      = 3600
BASE_ROLLS       = 10
MAX_CLAIMS_PER_HOUR = 1
MAX_STREAK_BONUS = 4
HAREM_PAGE_SIZE  = 15
BROWSE_PAGE_SIZE = 10
WISHLIST_MAX   = 10

FACTION_COLOR = {
    "reds":        0xA01414,
    "capitalists": 0x144696,
    "conquerors":  0x6E460F,
    "strongmen":   0x461450,
    "philosophers":0x0F5A50,
    "icons":       0xC8860A,
    "wildcards":   0x505014,
}

FACTION_LABEL = {
    "reds":        "THE REDS",
    "capitalists": "THE CAPITALISTS",
    "conquerors":  "THE CONQUERORS",
    "strongmen":   "THE STRONGMEN",
    "philosophers":"PHILOSOPHERS",
    "icons":       "ICONS",
    "wildcards":   "WILDCARDS",
}

RARITY_STARS = {
    "legendary": 5,
    "epic":      4,
    "rare":      3,
    "uncommon":  2,
    "common":    1,
}

RARITY_ORDER  = ["legendary", "epic", "rare", "uncommon", "common"]
FACTION_ORDER = list(FACTION_LABEL.keys())

RARITY_EMOJI = {
    "legendary": "🟡",
    "epic":      "🟣",
    "rare":      "🔵",
    "uncommon":  "🟢",
    "common":    "⚪",
}

DUPE_YUAN = {
    "legendary": 5000,
    "epic":      2000,
    "rare":      800,
    "uncommon":  300,
    "common":    100,
}

DUPE_COLOR  = 0xB8860B
DUPE_EMOJI  = "💴"


# ── Autocomplete ───────────────────────────────────────────────────────────────

async def _figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    q = current.lower()
    results = [
        (cid, ch) for cid, ch in _CHARS.items()
        if q in ch["name"].lower() or q in cid
    ]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(
            name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}",
            value=cid,
        )
        for cid, ch in results[:25]
    ]


async def _owned_figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete limited to waifus the invoking user owns in this guild."""
    if not interaction.guild:
        return []
    db = interaction.client.db
    rows = await db.get_user_collection(interaction.guild.id, interaction.user.id)
    owned_ids = {r["character_id"] for r in rows}
    q = current.lower()
    results = [
        (cid, _CHARS[cid]) for cid in owned_ids
        if cid in _CHARS and (q in _CHARS[cid]["name"].lower() or q in cid)
    ]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(
            name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}",
            value=cid,
        )
        for cid, ch in results[:25]
    ]


async def _wishlist_figure_ac(
    interaction: discord.Interaction, current: str
) -> list[app_commands.Choice[str]]:
    """Autocomplete limited to waifus on the user's wishlist."""
    if not interaction.guild:
        return []
    db = interaction.client.db
    ids = await db.get_wishlist(interaction.guild.id, interaction.user.id)
    q = current.lower()
    results = [
        (cid, _CHARS[cid]) for cid in ids
        if cid in _CHARS and (q in _CHARS[cid]["name"].lower() or q in cid)
    ]
    results.sort(key=lambda x: (not x[1]["name"].lower().startswith(q), x[1]["name"]))
    return [
        app_commands.Choice(
            name=f"{RARITY_EMOJI.get(ch['rarity'], '')} {ch['name']}",
            value=cid,
        )
        for cid, ch in results[:25]
    ]


# ── Embed helpers ──────────────────────────────────────────────────────────────

def _pick_image(char: dict) -> str | None:
    urls = char.get("image_urls") or []
    return random.choice(urls) if urls else None


def _stars(rarity: str) -> str:
    n = RARITY_STARS.get(rarity, 1)
    return "★" * n + "☆" * (5 - n)


def _roll_embed(char: dict, image_url: str | None, rolls_remaining: int, max_rolls: int, dupe: bool = False, owner_name: str | None = None) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    rolls_part = f"⚠️ {rolls_remaining}/{max_rolls} rolls remaining" if rolls_remaining <= 2 else f"{rolls_remaining}/{max_rolls} rolls remaining"
    color = DUPE_COLOR if dupe else FACTION_COLOR.get(char["faction"], 0xCC0000)
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {_stars(char['rarity'])}",
        color=color,
    )
    if image_url:
        embed.set_image(url=image_url)
    if dupe:
        belongs = f"Belongs to {owner_name}  ·  " if owner_name else ""
        embed.set_footer(text=f"{belongs}{rolls_part}")
    else:
        embed.set_footer(text=f"React with any emoji to claim!  ·  {rolls_part}")
    return embed


def _claimed_embed(char: dict, image_url: str | None, claimer_name: str, rank: int | None = None) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    rank_part = f"  ·  Global #{rank}" if rank else ""
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {_stars(char['rarity'])}",
        color=0xFF69B4,
    )
    if image_url:
        embed.set_image(url=image_url)
    embed.set_footer(text=f"Claimed by {claimer_name}{rank_part}")
    return embed


# ── Browse ─────────────────────────────────────────────────────────────────────

def _all_chars(faction: str | None = None, rarity: str | None = None) -> list[tuple[str, dict]]:
    items = list(_CHARS.items())
    if faction:
        items = [(k, v) for k, v in items if v["faction"] == faction]
    if rarity:
        items = [(k, v) for k, v in items if v["rarity"] == rarity]
    items.sort(key=lambda x: (RARITY_ORDER.index(x[1]["rarity"]), x[1]["name"]))
    return items


def _browse_embed(
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

    lines = []
    for char_id, char in page_items:
        check = "✓" if char_id in owned else "·"
        lines.append(f"`{check}` {_stars(char['rarity'])} **{char['name']}** — {char['title']}")

    embed = discord.Embed(
        title=title,
        description="\n".join(lines) or "No waifus match.",
        color=0xCC0000,
    )
    embed.set_footer(text=f"Page {page + 1}/{total_pages}  ·  ✓ = owned")
    return embed


class BrowseView(discord.ui.View):
    def __init__(self, items: list[tuple[str, dict]], owned: set[str], faction: str | None, rarity: str | None):
        super().__init__(timeout=120)
        self.items   = items
        self.owned   = owned
        self.faction = faction
        self.rarity  = rarity
        self.page    = 0
        self.total   = max(1, (len(items) + BROWSE_PAGE_SIZE - 1) // BROWSE_PAGE_SIZE)
        self._refresh_buttons()

    def _page_items(self) -> list[tuple[str, dict]]:
        s = self.page * BROWSE_PAGE_SIZE
        return self.items[s:s + BROWSE_PAGE_SIZE]

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total - 1

    def build_embed(self) -> discord.Embed:
        return _browse_embed(self._page_items(), self.page, self.total, self.faction, self.rarity, self.owned)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page -= 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.page += 1
        self._refresh_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ── Harem ──────────────────────────────────────────────────────────────────────

class HaremView(discord.ui.View):
    def __init__(
        self,
        entries: list[tuple[str, dict]],
        user_name: str,
        thumb_url: str | None,
        icon_url: str | None,
        total: int,
    ):
        super().__init__(timeout=120)
        self.entries       = entries
        self.user_name     = user_name
        self.thumb_url     = thumb_url
        self.icon_url      = icon_url
        self.total         = total
        self.page          = 0
        self.faction_filter: str | None = None
        self.filtered      = entries
        self._rebuild()

    @property
    def _total_pages(self) -> int:
        return max(1, (len(self.filtered) + HAREM_PAGE_SIZE - 1) // HAREM_PAGE_SIZE)

    def _rebuild(self):
        self.clear_items()

        factions = sorted({ch["faction"] for _, ch in self.entries})
        options  = [discord.SelectOption(label="All Factions", value="all", default=self.faction_filter is None)]
        for f in factions:
            options.append(discord.SelectOption(
                label=FACTION_LABEL.get(f, f.upper()),
                value=f,
                default=self.faction_filter == f,
            ))
        sel = discord.ui.Select(placeholder="Filter by faction…", options=options, row=0)
        sel.callback = self._on_faction
        self.add_item(sel)

        prev = discord.ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0, row=1)
        prev.callback = self._on_prev
        self.add_item(prev)

        nxt = discord.ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self._total_pages - 1, row=1)
        nxt.callback = self._on_next
        self.add_item(nxt)

    async def _on_faction(self, interaction: discord.Interaction):
        value = interaction.data["values"][0]
        self.faction_filter = None if value == "all" else value
        self.filtered = [(cid, ch) for cid, ch in self.entries if self.faction_filter is None or ch["faction"] == self.faction_filter]
        self.page = 0
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(embed=self._build_embed(), view=self)

    def _build_embed(self) -> discord.Embed:
        start = self.page * HAREM_PAGE_SIZE
        page_entries = self.filtered[start:start + HAREM_PAGE_SIZE]
        lines = [f"{_stars(ch['rarity'])} **{ch['name']}**" for _, ch in page_entries]
        embed = discord.Embed(
            description=f"{self.total} waifu{'s' if self.total != 1 else ''} collected",
            color=0xCC0000,
        )
        embed.set_author(name=f"{self.user_name}'s Harem", icon_url=self.icon_url)
        if self.thumb_url:
            embed.set_thumbnail(url=self.thumb_url)
        embed.add_field(name="", value="\n".join(lines) or "No waifus match.", inline=False)
        embed.set_footer(text=f"Page {self.page + 1}/{self._total_pages}")
        return embed

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True


# ── Trade ──────────────────────────────────────────────────────────────────────

class TradeView(discord.ui.View):
    def __init__(self, offerer: discord.Member, target: discord.Member, offer_id: str, request_id: str):
        super().__init__(timeout=120)
        self.offerer    = offerer
        self.target     = target
        self.offer_id   = offer_id
        self.request_id = request_id

    async def _finish(self, interaction: discord.Interaction, accepted: bool):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass

        if accepted:
            ok = await interaction.client.db.trade_characters(
                interaction.guild.id,
                self.offerer.id, self.offer_id,
                self.target.id,  self.request_id,
            )
            if ok:
                offer_char   = _get_personality(self.offer_id)
                request_char = _get_personality(self.request_id)
                embed = discord.Embed(
                    title="Trade Complete",
                    description=(
                        f"{self.offerer.mention} received **{request_char['name']}**\n"
                        f"{self.target.mention} received **{offer_char['name']}**"
                    ),
                    color=0x00AA44,
                )
                bot = interaction.client
                guild = interaction.guild
                await asyncio.gather(
                    unlock_achievement(bot, guild, self.offerer, "first_waifu_trade"),
                    unlock_achievement(bot, guild, self.target,  "first_waifu_trade"),
                )
            else:
                embed = discord.Embed(
                    title="Trade Failed",
                    description="One of the waifus is no longer available. Trade cancelled.",
                    color=0xAA0000,
                )
        else:
            embed = discord.Embed(
                title="Trade Declined",
                description=f"{self.target.mention} declined the trade.",
                color=0x888888,
            )

        await interaction.edit_original_response(embed=embed, view=self)
        self.stop()

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("Only the trade target can accept.", ephemeral=True)
            return
        await self._finish(interaction, True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id not in (self.target.id, self.offerer.id):
            await interaction.response.send_message("Not your trade.", ephemeral=True)
            return
        await self._finish(interaction, False)


# ── Image view ─────────────────────────────────────────────────────────────────

def _image_embed(char: dict, url: str, index: int, total: int, rank_text: str) -> discord.Embed:
    faction_label = FACTION_LABEL.get(char["faction"], char["faction"].upper())
    page = f"  ·  {index + 1}/{total}" if total > 1 else ""
    embed = discord.Embed(
        title=char["name"],
        description=f"{char['title']}\n{faction_label}  ·  {_stars(char['rarity'])}",
        color=FACTION_COLOR.get(char["faction"], 0xCC0000),
    )
    embed.set_image(url=url)
    embed.set_footer(text=f"{rank_text}{page}")
    return embed


class ImageView(discord.ui.View):
    def __init__(self, char: dict, urls: list[str], rank_text: str):
        super().__init__(timeout=120)
        self.char      = char
        self.urls      = urls
        self.rank_text = rank_text
        self.index     = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.urls) - 1

    def build_embed(self) -> discord.Embed:
        return _image_embed(self.char, self.urls[self.index], self.index, len(self.urls), self.rank_text)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index -= 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index += 1
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


# ── Cog ────────────────────────────────────────────────────────────────────────

class GachaCog(commands.Cog, name="Gacha"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        global _CHARS
        _CHARS = await self.db.get_all_characters()
        print(f"[gacha] loaded {len(_CHARS)} characters from DB")

    async def reload_chars(self) -> int:
        global _CHARS
        _CHARS = await self.db.get_all_characters()
        return len(_CHARS)

    # ── roll helpers ─────────────────────────────────────────────────────────

    async def _max_rolls(self, user_id: int) -> int:
        streak = await self.db.get_counter(user_id, "topgg_vote_streak:current") or 0
        return BASE_ROLLS + min(int(streak), MAX_STREAK_BONUS)

    async def _roll_state(self, guild_id: int, user_id: int) -> tuple[int, int]:
        r = get_redis()
        key = f"gacha:rolls:{guild_id}:{user_id}"
        raw, ttl = await asyncio.gather(r.get(key), r.ttl(key))
        return (int(raw) if raw else 0), max(int(ttl), 0)

    async def _increment_rolls(self, guild_id: int, user_id: int) -> int:
        r = get_redis()
        key = f"gacha:rolls:{guild_id}:{user_id}"
        new_count = await r.incr(key)
        if new_count == 1:
            secs_to_next_hour = 3600 - (int(time.time()) % 3600)
            await r.expire(key, secs_to_next_hour)
        return new_count

    async def _get_owner_cached(self, guild_id: int, char_id: str) -> int | None:
        r = get_redis()
        key = f"gacha:owner:{guild_id}:{char_id}"
        cached = await r.get(key)
        if cached is not None:
            return int(cached) if cached != b"0" and cached != "0" else None
        owner_id = await self.db.get_character_owner(guild_id, char_id)
        await r.set(key, str(owner_id) if owner_id else "0", ex=300)
        return owner_id

    async def _set_owner_cache(self, guild_id: int, char_id: str, owner_id: int | None):
        r = get_redis()
        key = f"gacha:owner:{guild_id}:{char_id}"
        await r.set(key, str(owner_id) if owner_id else "0", ex=300)

    # ── shared logic ─────────────────────────────────────────────────────────

    async def _do_roll(self, guild_id: int, user_id: int, display_name: str, send_fn):
        (max_rolls, (rolls_used, ttl)) = await asyncio.gather(
            self._max_rolls(user_id),
            self._roll_state(guild_id, user_id),
        )

        if rolls_used >= max_rolls:
            mins = max(1, (ttl + 59) // 60)
            vote_bonus = max_rolls - BASE_ROLLS
            limit_note = f" (+{vote_bonus} from vote streak)" if vote_bonus else ""
            await send_fn(
                f"**{display_name}**, the roulette is limited to "
                f"**{max_rolls}** uses per hour{limit_note}. **{mins} min** left.\n"
                f"Vote to reset your rolls and increase your limit: `ccp vote`"
            )
            return

        char_id, char = _roll_weighted()
        image_url = _pick_image(char)

        new_count, owner_id = await asyncio.gather(
            self._increment_rolls(guild_id, user_id),
            self._get_owner_cached(guild_id, char_id),
        )
        rolls_remaining = max_rolls - new_count
        dupe = owner_id is not None

        owner_name: str | None = None
        if dupe:
            guild_obj = self.bot.get_guild(guild_id)
            member = guild_obj.get_member(owner_id) if guild_obj else None
            if member:
                owner_name = member.display_name
            else:
                try:
                    user = await self.bot.fetch_user(owner_id)
                    owner_name = user.display_name
                except Exception:
                    owner_name = None

        embed = _roll_embed(char, image_url, rolls_remaining, max_rolls, dupe=dupe, owner_name=owner_name)
        msg = await send_fn(embed=embed)

        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild else None
        if guild and member:
            await unlock_achievement(self.bot, guild, member, "first_roll")

        r = get_redis()
        pending = json.dumps({
            "char_id":   char_id,
            "guild_id":  guild_id,
            "image_url": image_url or "",
            "dupe":      dupe,
        })
        await r.set(f"gacha:pending:{msg.id}", pending, ex=CLAIM_WINDOW)

        if not dupe:
            jump_url = getattr(msg, "jump_url", None)
            guild = self.bot.get_guild(guild_id)
            if jump_url and guild:
                watchers = await self.db.get_wishlist_watchers(guild_id, char_id)
                for watcher_id in watchers:
                    if watcher_id == user_id:
                        continue
                    try:
                        watcher = guild.get_member(watcher_id) or await self.bot.fetch_user(watcher_id)
                        await watcher.send(
                            f"**{char['name']}** {_stars(char['rarity'])} from your wishlist just appeared in **{guild.name}**!\n"
                            f"{jump_url}"
                        )
                    except (discord.Forbidden, discord.HTTPException):
                        pass


    async def _show_top(self, send_fn):
        rows = await self.db.get_top_characters(15)
        if not rows:
            await send_fn("No waifus have been claimed yet.")
            return
        lines = []
        for row in rows:
            char = _get_personality(row["character_id"])
            if not char:
                continue
            lines.append(
                f"`#{row['rank']}` {_stars(char['rarity'])} **{char['name']}** — {row['claim_count']} claims"
            )
        embed = discord.Embed(
            title="Most Claimed Waifus · Global",
            description="\n".join(lines) or "None yet.",
            color=0xCC0000,
        )
        await send_fn(embed=embed)

    async def _do_wishlist_view(self, guild_id: int, target: discord.Member | discord.User, send_fn):
        ids = await self.db.get_wishlist(guild_id, target.id)
        if not ids:
            name = target.display_name if hasattr(target, "display_name") else str(target)
            await send_fn(f"**{name}** has no waifus on their wishlist.")
            return

        rows = await self.db.get_user_collection(guild_id, target.id)
        owned = {r["character_id"] for r in rows}

        lines = []
        for char_id in ids:
            char = _get_personality(char_id)
            if not char:
                continue
            check = "✓" if char_id in owned else "·"
            lines.append(f"`{check}` {_stars(char['rarity'])} **{char['name']}** — {char['title']}")

        name = target.display_name if hasattr(target, "display_name") else str(target)
        embed = discord.Embed(
            title=f"{name}'s Wishlist",
            description="\n".join(lines) or "Empty.",
            color=0xCC0000,
        )
        embed.set_footer(text="✓ = already owned")
        await send_fn(embed=embed)

    # ── slash: roll / image / collection ─────────────────────────────────────

    @app_commands.command(name="roll", description="Roll for a random historical waifu")
    async def slash_roll(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._do_roll(
            interaction.guild.id, interaction.user.id,
            interaction.user.display_name, interaction.followup.send,
        )

    @app_commands.command(name="image", description="View a personality's card")
    @app_commands.describe(name="Name of the historical waifu")
    @app_commands.autocomplete(name=_figure_ac)
    async def slash_image(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        await self._show_card(name, interaction.followup.send)

    @app_commands.command(name="harem", description="View your harem")
    @app_commands.describe(user="View another member's harem")
    async def slash_collection(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        await self._show_collection(interaction.guild.id, user or interaction.user, interaction.followup.send)

    @app_commands.command(name="choose", description="Set your featured harem thumbnail")
    @app_commands.describe(name="Name of the waifu to feature")
    async def slash_choose(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        await self._do_choose(interaction.guild.id, interaction.user, name, interaction.followup.send)

    # ── slash: top ────────────────────────────────────────────────────────────

    @app_commands.command(name="top", description="Global leaderboard of most-claimed waifus")
    async def slash_top(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self._show_top(interaction.followup.send)

    # ── slash: browse ─────────────────────────────────────────────────────────

    @app_commands.command(name="browse", description="Browse all available waifus")
    @app_commands.describe(faction="Filter by faction", rarity="Filter by rarity")
    @app_commands.choices(
        faction=[app_commands.Choice(name=FACTION_LABEL[f], value=f) for f in FACTION_ORDER],
        rarity=[app_commands.Choice(name=r.capitalize(), value=r) for r in RARITY_ORDER],
    )
    async def slash_browse(
        self,
        interaction: discord.Interaction,
        faction: str | None = None,
        rarity: str | None = None,
    ):
        await interaction.response.defer()
        items = _all_chars(faction, rarity)
        rows  = await self.db.get_user_collection(interaction.guild.id, interaction.user.id)
        owned = {r["character_id"] for r in rows}
        view  = BrowseView(items, owned, faction, rarity)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # ── slash: trade ──────────────────────────────────────────────────────────

    @app_commands.command(name="trade", description="Offer a waifu trade to another member")
    @app_commands.describe(
        user="The member to trade with",
        offer="The waifu you're giving away",
        request="The waifu you want in return",
    )
    @app_commands.autocomplete(offer=_owned_figure_ac, request=_figure_ac)
    async def slash_trade(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
        offer: str,
        request: str,
    ):
        await interaction.response.defer()

        if user.id == interaction.user.id:
            await interaction.followup.send("You can't trade with yourself.")
            return
        if user.bot:
            await interaction.followup.send("You can't trade with a bot.")
            return

        offer_char   = _get_personality(offer) or _search_personality(offer)
        request_char = _get_personality(request) or _search_personality(request)

        if not offer_char:
            await interaction.followup.send(f"No waifu found matching **{offer}**.")
            return
        if not request_char:
            await interaction.followup.send(f"No waifu found matching **{request}**.")
            return

        offer_id   = offer_char.get("id", offer) if "id" in (offer_char or {}) else offer
        request_id = request_char.get("id", request) if "id" in (request_char or {}) else request

        # normalise: search_personality adds "id", get_personality doesn't
        if "id" not in offer_char:
            offer_id = offer
            offer_char = {**offer_char, "id": offer_id}
        if "id" not in request_char:
            request_id = request
            request_char = {**request_char, "id": request_id}

        guild_id = interaction.guild.id

        if not await self.db.has_character(guild_id, interaction.user.id, offer_id):
            await interaction.followup.send(f"You don't own **{offer_char['name']}**.")
            return
        if not await self.db.has_character(guild_id, user.id, request_id):
            await interaction.followup.send(f"{user.display_name} doesn't own **{request_char['name']}**.")
            return

        embed = discord.Embed(
            title="Trade Offer",
            description=(
                f"{interaction.user.mention} offers **{offer_char['name']}** {_stars(offer_char['rarity'])}\n"
                f"in exchange for **{request_char['name']}** {_stars(request_char['rarity'])}\n\n"
                f"{user.mention}, do you accept?"
            ),
            color=FACTION_COLOR.get(offer_char["faction"], 0xCC0000),
        )
        if img := _pick_image(offer_char):
            embed.set_thumbnail(url=img)

        view = TradeView(interaction.user, user, offer_id, request_id)
        await interaction.followup.send(embed=embed, view=view)

    # ── slash: gift ───────────────────────────────────────────────────────────

    @app_commands.command(name="gift", description="Give one of your waifus to another member")
    @app_commands.describe(waifu="The waifu you want to give", user="Who to give it to")
    @app_commands.autocomplete(waifu=_owned_figure_ac)
    async def slash_gift(self, interaction: discord.Interaction, waifu: str, user: discord.Member):
        await interaction.response.defer()

        if user.id == interaction.user.id:
            await interaction.followup.send("You can't gift to yourself.")
            return
        if user.bot:
            await interaction.followup.send("You can't gift to a bot.")
            return

        char = _get_personality(waifu) or _search_personality(waifu)
        if not char:
            await interaction.followup.send(f"No waifu found matching **{waifu}**.")
            return
        char_id = char.get("id", waifu)

        ok = await self.db.gift_character(interaction.guild.id, interaction.user.id, user.id, char_id)
        if not ok:
            await interaction.followup.send(f"You don't own **{char['name']}**.")
            return

        embed = discord.Embed(
            title="Waifu Gifted",
            description=(
                f"{interaction.user.mention} gifted **{char['name']}** {_stars(char['rarity'])}\n"
                f"to {user.mention}"
            ),
            color=FACTION_COLOR.get(char["faction"], 0xCC0000),
        )
        if img := _pick_image(char):
            embed.set_thumbnail(url=img)
        await interaction.followup.send(embed=embed)

    # ── slash: wishlist group ─────────────────────────────────────────────────

    wishlist_group = app_commands.Group(name="wishlist", description="Manage your waifu wishlist")

    @wishlist_group.command(name="add", description="Add a waifu to your wishlist")
    @app_commands.describe(name="Waifu to wishlist")
    @app_commands.autocomplete(name=_figure_ac)
    async def wishlist_add(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        char = _get_personality(name) or _search_personality(name)
        if not char:
            await interaction.followup.send(f"No waifu found matching **{name}**.")
            return
        char_id = char.get("id", name)

        current = await self.db.get_wishlist(interaction.guild.id, interaction.user.id)
        if len(current) >= WISHLIST_MAX:
            await interaction.followup.send(f"Your wishlist is full ({WISHLIST_MAX} max). Remove one first.")
            return

        added = await self.db.add_wishlist(interaction.guild.id, interaction.user.id, char_id)
        if added:
            await interaction.followup.send(f"Added **{char['name']}** {_stars(char['rarity'])} to your wishlist.")
        else:
            await interaction.followup.send(f"**{char['name']}** is already on your wishlist.")

    @wishlist_group.command(name="remove", description="Remove a waifu from your wishlist")
    @app_commands.describe(name="Waifu to remove")
    @app_commands.autocomplete(name=_wishlist_figure_ac)
    async def wishlist_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        char = _get_personality(name) or _search_personality(name)
        if not char:
            await interaction.followup.send(f"No waifu found matching **{name}**.")
            return
        char_id = char.get("id", name)

        removed = await self.db.remove_wishlist(interaction.guild.id, interaction.user.id, char_id)
        if removed:
            await interaction.followup.send(f"Removed **{char['name']}** from your wishlist.")
        else:
            await interaction.followup.send(f"**{char['name']}** wasn't on your wishlist.")

    @wishlist_group.command(name="view", description="View a wishlist")
    @app_commands.describe(user="View another member's wishlist")
    async def wishlist_view(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        await self._do_wishlist_view(interaction.guild.id, user or interaction.user, interaction.followup.send)

    # ── prefix: roll / image / collection ────────────────────────────────────

    @commands.command(name="roll", aliases=["r"])
    async def prefix_roll(self, ctx: commands.Context):
        async with ctx.typing():
            await self._do_roll(ctx.guild.id, ctx.author.id, ctx.author.display_name, ctx.send)

    @commands.command(name="image")
    async def prefix_image(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await ctx.send("Usage: `ccp image <waifu name>`")
                return
            await self._show_card(name, ctx.send)

    @commands.command(name="harem", aliases=["collection"])
    async def prefix_collection(self, ctx: commands.Context, user: discord.Member = None):
        async with ctx.typing():
            await self._show_collection(ctx.guild.id, user or ctx.author, ctx.send)

    @commands.command(name="choose")
    async def prefix_choose(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await ctx.send("Usage: `ccp choose <waifu name>`")
                return
            await self._do_choose(ctx.guild.id, ctx.author, name, ctx.send)

    @commands.command(name="top")
    async def prefix_top(self, ctx: commands.Context):
        async with ctx.typing():
            await self._show_top(ctx.send)

    @commands.command(name="gift")
    async def prefix_gift(self, ctx: commands.Context, name: str, *, user_str: str = ""):
        async with ctx.typing():
            # allow: ccp gift "waifu name" @user  OR  ccp gift figure_name @mention
            # resolve mention from the message directly
            target = ctx.message.mentions[0] if ctx.message.mentions else None
            if target is None:
                await ctx.send("Please mention the user to gift to: `ccp gift <waifu> @user`")
                return
            if target.id == ctx.author.id:
                await ctx.send("You can't gift to yourself.")
                return
            if target.bot:
                await ctx.send("You can't gift to a bot.")
                return

            char = _search_personality(name)
            if not char:
                await ctx.send(f"No waifu found matching **{name}**.")
                return

            ok = await self.db.gift_character(ctx.guild.id, ctx.author.id, target.id, char["id"])
            if not ok:
                await ctx.send(f"You don't own **{char['name']}**.")
                return

            embed = discord.Embed(
                title="Waifu Gifted",
                description=(
                    f"{ctx.author.mention} gifted **{char['name']}** {_stars(char['rarity'])}\n"
                    f"to {target.mention}"
                ),
                color=FACTION_COLOR.get(char["faction"], 0xCC0000),
            )
            if img := _pick_image(char):
                embed.set_thumbnail(url=img)
            await ctx.send(embed=embed)

    # ── prefix: wishlist ──────────────────────────────────────────────────────

    @commands.command(name="wish")
    async def prefix_wish(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await self._do_wishlist_view(ctx.guild.id, ctx.author, ctx.send)
                return
            char = _search_personality(name)
            if not char:
                await ctx.send(f"No waifu found matching **{name}**.")
                return
            char_id = char["id"]
            current = await self.db.get_wishlist(ctx.guild.id, ctx.author.id)
            if len(current) >= WISHLIST_MAX:
                await ctx.send(f"Your wishlist is full ({WISHLIST_MAX} max). Remove one first.")
                return
            added = await self.db.add_wishlist(ctx.guild.id, ctx.author.id, char_id)
            if added:
                await ctx.send(f"Added **{char['name']}** {_stars(char['rarity'])} to your wishlist.")
            else:
                await ctx.send(f"**{char['name']}** is already on your wishlist.")

    @commands.command(name="wl", aliases=["wishlist"])
    async def prefix_wl(self, ctx: commands.Context):
        async with ctx.typing():
            await self._do_wishlist_view(ctx.guild.id, ctx.author, ctx.send)

    # ── divorce ───────────────────────────────────────────────────────────────

    async def _do_divorce(self, guild_id: int, user_id: int, name: str, send_fn):
        char = _get_personality(name) or _search_personality(name)
        if not char:
            await send_fn(f"No waifu found matching **{name}**.")
            return
        char_id = char.get("id", name)
        ok, _ = await asyncio.gather(
            self.db.divorce_character(guild_id, user_id, char_id),
            self._set_owner_cache(guild_id, char_id, None),
        )
        if not ok:
            await send_fn(f"You don't have **{char['name']}** in your harem.")
            return
        await send_fn(f"💔 **{char['name']}** has been removed from your harem.")
        guild = self.bot.get_guild(guild_id)
        member = guild.get_member(user_id) if guild else None
        if guild and member:
            divorces = await self.db.increment_counter(user_id, "gacha_divorces")
            await asyncio.gather(
                unlock_achievement(self.bot, guild, member, "first_divorce"),
                check_milestone(self.bot, guild, member, "gacha_divorces", divorces),
            )

    @app_commands.command(name="divorce", description="Remove a waifu from your harem")
    @app_commands.describe(name="Waifu to divorce")
    @app_commands.autocomplete(name=_owned_figure_ac)
    async def slash_divorce(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        await self._do_divorce(interaction.guild.id, interaction.user.id, name, interaction.followup.send)

    @commands.command(name="divorce")
    async def prefix_divorce(self, ctx: commands.Context, *, name: str):
        async with ctx.typing():
            await self._do_divorce(ctx.guild.id, ctx.author.id, name, ctx.send)

    # ── claim handler ─────────────────────────────────────────────────────────

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_claim(self, payload: discord.RawReactionActionEvent):
        if payload.user_id == self.bot.user.id:
            return
        if not payload.guild_id:
            return

        r = get_redis()
        key = f"gacha:pending:{payload.message_id}"

        ttl = await r.ttl(key)
        raw = await r.getdel(key)
        if raw is None:
            return

        claim_key = f"gacha:claims:{payload.guild_id}:{payload.user_id}"
        claims_used = await r.incr(claim_key)
        if claims_used == 1:
            secs_to_next_hour = 3600 - (int(time.time()) % 3600)
            await r.expire(claim_key, secs_to_next_hour)
        if claims_used > MAX_CLAIMS_PER_HOUR:
            await r.decr(claim_key)
            await r.set(key, raw, ex=max(1, ttl))
            try:
                channel = self.bot.get_channel(payload.channel_id) or await self.bot.fetch_channel(payload.channel_id)
                mins = max(1, (await r.ttl(claim_key) + 59) // 60)
                await channel.send(
                    f"<@{payload.user_id}> You've already claimed your character for this hour. **{mins} min** left.",
                    delete_after=10,
                )
            except (discord.NotFound, discord.HTTPException):
                pass
            return

        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return

        char_id   = data["char_id"]
        image_url = data.get("image_url") or None
        guild_id  = data["guild_id"]
        is_dupe   = data.get("dupe", False)

        char = _get_personality(char_id)
        if not char:
            return

        claimer_id = payload.user_id

        guild   = self.bot.get_guild(guild_id)
        claimer = guild.get_member(claimer_id) if guild else None
        if claimer is None:
            try:
                claimer = await self.bot.fetch_user(claimer_id)
            except Exception:
                return

        claimer_name = claimer.display_name if hasattr(claimer, "display_name") else str(claimer)

        if is_dupe:
            yuan = DUPE_YUAN.get(char["rarity"], 100)
            await self.db.adjust_yuan(guild_id, claimer_id, yuan)
            try:
                channel = self.bot.get_channel(payload.channel_id)
                if channel is None:
                    channel = await self.bot.fetch_channel(payload.channel_id)
                await channel.send(
                    f"**{claimer_name}** +¥{yuan:,}",
                    reference=discord.MessageReference(message_id=payload.message_id, channel_id=payload.channel_id, fail_if_not_exists=False),
                )
            except (discord.NotFound, discord.HTTPException):
                pass
            if guild and isinstance(claimer, discord.Member):
                await unlock_achievement(self.bot, guild, claimer, "first_dupe")
            return

        await asyncio.gather(
            self.db.claim_character(guild_id, claimer_id, char_id),
            self._set_owner_cache(guild_id, char_id, claimer_id),
        )
        rank_info = await self.db.get_character_rank(char_id)

        try:
            channel = self.bot.get_channel(payload.channel_id)
            if channel is None:
                channel = await self.bot.fetch_channel(payload.channel_id)
            message = await channel.fetch_message(payload.message_id)
            await message.edit(embed=_claimed_embed(char, image_url, claimer_name, rank_info["rank"]))
            await channel.send(f"**{claimer_name}** and **{char['name']}** are now married ❤️")
        except (discord.NotFound, discord.HTTPException):
            pass

        if guild and isinstance(claimer, discord.Member):
            wishlist = await self.db.get_wishlist(guild_id, claimer_id)
            total = await self.db.increment_counter(claimer_id, "gacha_claims_total")
            await asyncio.gather(
                unlock_achievement(self.bot, guild, claimer, "first_claim"),
                check_milestone(self.bot, guild, claimer, "gacha_claims_total", total),
                *(
                    [unlock_achievement(self.bot, guild, claimer, "claimed_legendary")]
                    if char.get("rarity") == "legendary" else []
                ),
                *(
                    [unlock_achievement(self.bot, guild, claimer, "wishlist_fulfilled")]
                    if char_id in wishlist else []
                ),
            )

        watchers = await self.db.get_wishlist_watchers(guild_id, char_id)
        for watcher_id in watchers:
            if watcher_id == claimer_id:
                continue
            try:
                watcher = guild.get_member(watcher_id) if guild else None
                if watcher is None:
                    watcher = await self.bot.fetch_user(watcher_id)
                await watcher.send(
                    f"**{char['name']}** {_stars(char['rarity'])} from your wishlist was just claimed by "
                    f"**{claimer_name}** in **{guild.name if guild else 'a server'}**!"
                )
            except (discord.Forbidden, discord.HTTPException):
                pass

    # ── image view ────────────────────────────────────────────────────────────

    async def _show_card(self, name: str, send_fn):
        char = _get_personality(name) or _search_personality(name)
        if not char:
            await send_fn(f"No waifu found matching **{name}**.")
            return
        char_id = char.get("id", name)
        urls = char.get("image_urls") or []
        if not urls:
            await send_fn(f"No image available for **{char['name']}**.")
            return

        rank_info = await self.db.get_character_rank(char_id)
        rank_text = f"Global #{rank_info['rank']}  ·  {rank_info['claims']} claims" if rank_info["rank"] else "Unclaimed globally"

        if len(urls) == 1:
            embed = _image_embed(char, urls[0], 0, len(urls), rank_text)
            await send_fn(embed=embed)
        else:
            view = ImageView(char, urls, rank_text)
            await send_fn(embed=view.build_embed(), view=view)

    # ── collection view ───────────────────────────────────────────────────────

    async def _show_collection(self, guild_id: int, user: discord.Member | discord.User, send_fn):
        rows = await self.db.get_user_collection(guild_id, user.id)
        name = user.display_name if hasattr(user, "display_name") else str(user)
        if not rows:
            await send_fn(f"**{name}** has no waifus yet. Use `/roll` to start collecting!")
            return

        chosen_id = await self.db.get_harem_thumbnail(guild_id, user.id)
        thumb_char = _get_personality(chosen_id) if chosen_id else None
        if not thumb_char:
            for row in rows:
                c = _get_personality(row["character_id"])
                if c and c.get("image_urls"):
                    thumb_char = c
                    break

        thumb_url = _pick_image(thumb_char) if thumb_char else None
        icon_url  = user.display_avatar.url if hasattr(user, "display_avatar") else None

        entries = []
        for row in rows:
            char = _get_personality(row["character_id"])
            if char:
                entries.append((row["character_id"], char))
        entries.sort(key=lambda x: (RARITY_ORDER.index(x[1].get("rarity", "common")), x[1]["name"]))

        if not entries:
            await send_fn(f"**{name}** has no waifus yet. Use `/roll` to start collecting!")
            return

        view = HaremView(entries, name, thumb_url, icon_url, len(entries))
        await send_fn(embed=view._build_embed(), view=view)

    async def _do_choose(self, guild_id: int, user: discord.Member | discord.User, name: str, send_fn):
        char = _search_personality(name)
        if not char:
            await send_fn(f"No waifu found matching **{name}**.", ephemeral=True)
            return
        if not await self.db.has_character(guild_id, user.id, char["id"]):
            await send_fn(f"**{char['name']}** is not in your harem.", ephemeral=True)
            return
        await self.db.set_harem_thumbnail(guild_id, user.id, char["id"])
        await send_fn(f"**{char['name']}** is now your featured waifu.")


async def setup(bot: commands.Bot):
    await bot.add_cog(GachaCog(bot))
