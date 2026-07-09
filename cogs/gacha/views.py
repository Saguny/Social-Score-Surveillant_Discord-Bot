import asyncio
import random

import discord

from . import characters
from .constants import (
    CLAIM_WINDOW, DUPE_YUAN, DIVORCE_YUAN, FACTION_COLOR, FACTION_LABEL, SUBMIT_URL,
    HAREM_PAGE_SIZE, BROWSE_PAGE_SIZE,
)
from .embeds import stars, pick_image, image_embed, harem_image_embed, browse_embed


class BrowseView(discord.ui.View):
    def __init__(
        self,
        items: list[tuple[str, dict]],
        owned: set[str],
        faction: str | None,
        rarity: str | None,
    ):
        super().__init__(timeout=120)
        self.items   = items
        self.owned   = owned
        self.faction = faction
        self.rarity  = rarity
        self.page    = 0
        self.total   = max(1, (len(items) + BROWSE_PAGE_SIZE - 1) // BROWSE_PAGE_SIZE)
        self._refresh_buttons()

    def _page_slice(self) -> list[tuple[str, dict]]:
        s = self.page * BROWSE_PAGE_SIZE
        return self.items[s:s + BROWSE_PAGE_SIZE]

    def _refresh_buttons(self):
        self.prev_btn.disabled = self.page == 0
        self.next_btn.disabled = self.page >= self.total - 1

    def build_embed(self) -> discord.Embed:
        return browse_embed(self._page_slice(), self.page, self.total, self.faction, self.rarity, self.owned)

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
        self.entries        = entries
        self.user_name      = user_name
        self.thumb_url      = thumb_url
        self.icon_url       = icon_url
        self.total          = total
        self.page           = 0
        self.faction_filter: str | None = None
        self.filtered       = entries
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
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_prev(self, interaction: discord.Interaction):
        self.page -= 1
        self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    async def _on_next(self, interaction: discord.Interaction):
        self.page += 1
        self._rebuild()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    def build_embed(self) -> discord.Embed:
        start        = self.page * HAREM_PAGE_SIZE
        page_entries = self.filtered[start:start + HAREM_PAGE_SIZE]
        lines = [f"{stars(ch['rarity'])} **{ch['name']}**" for _, ch in page_entries]
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
                from cogs.achievements import unlock as unlock_achievement
                offer_char   = characters.get(self.offer_id)
                request_char = characters.get(self.request_id)
                embed = discord.Embed(
                    title="Trade Complete",
                    description=(
                        f"{self.offerer.mention} received **{request_char['name']}**\n"
                        f"{self.target.mention} received **{offer_char['name']}**"
                    ),
                    color=0x00AA44,
                )
                await asyncio.gather(
                    unlock_achievement(interaction.client, interaction.guild, self.offerer, "first_waifu_trade"),
                    unlock_achievement(interaction.client, interaction.guild, self.target,  "first_waifu_trade"),
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


class ImageView(discord.ui.View):
    def __init__(self, char: dict, urls: list[str], rank_text: str, owner_name: str | None = None):
        super().__init__(timeout=120)
        self.char       = char
        self.urls       = urls
        self.rank_text  = rank_text
        self.owner_name = owner_name
        self.index      = 0
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.index == 0
        self.next_btn.disabled = self.index >= len(self.urls) - 1

    def build_embed(self) -> discord.Embed:
        return image_embed(self.char, self.urls[self.index], self.index, len(self.urls), self.rank_text, self.owner_name)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = max(self.index - 1, 0)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = min(self.index + 1, len(self.urls) - 1)
        self._update_buttons()
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class ImageChoiceView(discord.ui.View):
    """Shown when a name matches more than one character."""

    def __init__(self, service, matches: list[dict], guild_id: int | None = None):
        super().__init__(timeout=60)
        self.service  = service
        self.guild_id = guild_id
        opts = [
            discord.SelectOption(
                label=ch["name"][:100],
                description=f"{FACTION_LABEL.get(ch['faction'], ch['faction'].upper())} · {stars(ch['rarity'])}"[:100],
                value=ch["id"],
            )
            for ch in matches[:25]
        ]
        sel = discord.ui.Select(placeholder="Multiple matches — choose one…", options=opts)
        sel.callback = self._on_select
        self.add_item(sel)
        self._sel = sel

    async def _on_select(self, interaction: discord.Interaction):
        cid  = self._sel.values[0]
        char = characters.get(cid)
        if not char:
            await interaction.response.edit_message(content="That waifu no longer exists.", embed=None, view=None)
            return
        guild_id = self.guild_id or (interaction.guild.id if interaction.guild else None)
        embed, view = await self.service.build_card(cid, {"id": cid, **char}, guild_id=guild_id)
        if embed is None:
            await interaction.response.edit_message(content=f"No image available for **{char['name']}**.", embed=None, view=None)
            return
        await interaction.response.edit_message(content=None, embed=embed, view=view)


class HaremImageView(discord.ui.View):
    def __init__(self, entries: list[tuple[str, dict, str, dict]], owner_id: int, owner_name: str):
        super().__init__(timeout=180)
        self.entries    = entries   # (char_id, char, image_url, rank_info)
        self.owner_id   = owner_id
        self.owner_name = owner_name
        self.index      = 0

    def build_embed(self) -> discord.Embed:
        char_id, char, img_url, rank_info = self.entries[self.index]
        return harem_image_embed(char, img_url, rank_info, self.index, len(self.entries), self.owner_name)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message("This isn't your harem.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index - 1) % len(self.entries)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        self.index = (self.index + 1) % len(self.entries)
        await interaction.response.edit_message(embed=self.build_embed(), view=self)


class DupeYuanView(discord.ui.View):
    def __init__(self, char: dict, guild_id: int, roller_id: int):
        super().__init__(timeout=CLAIM_WINDOW)
        self._char       = char
        self._guild_id   = guild_id
        self._roller_id  = roller_id
        self.message_id: int | None = None  # set in rolls.py after send

    @discord.ui.button(emoji="💰", style=discord.ButtonStyle.secondary)
    async def collect(self, interaction: discord.Interaction, button: discord.ui.Button):
        from . import cache as _cache
        data, _ = await _cache.pop_pending(self.message_id)
        if data is None:
            await interaction.response.send_message("Already collected.", ephemeral=True)
            return
        self.stop()
        claimer_id = interaction.user.id
        lo, hi = DUPE_YUAN.get(self._char["rarity"], (50, 175))
        yuan = random.randint(lo, hi)
        await interaction.client.db.adjust_yuan(self._guild_id, claimer_id, yuan)
        button.disabled = True
        button.emoji = discord.PartialEmoji(name="✅")
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"**{interaction.user.display_name}** +¥{yuan:,} · duplicate payout")


class DivorceConfirmView(discord.ui.View):
    def __init__(self, bot, guild_id: int, user_id: int, char: dict, yuan: int):
        super().__init__(timeout=60)
        self._bot      = bot
        self._guild_id = guild_id
        self._user_id  = user_id
        self._char     = char
        self._yuan     = yuan

    def _disable_all(self):
        for child in self.children:
            child.disabled = True

    @discord.ui.button(label="Divorce", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("This isn't your divorce.", ephemeral=True)
            return
        self.stop()
        char_id = self._char.get("id")
        from . import cache as _cache
        ok, _ = await asyncio.gather(
            self._bot.db.divorce_character(self._guild_id, self._user_id, char_id),
            _cache.set_owner(self._guild_id, char_id, None),
        )
        self._disable_all()
        if not ok:
            await interaction.response.edit_message(
                content=f"**{self._char['name']}** is no longer in your harem.", view=self
            )
            return
        await self._bot.db.adjust_yuan(self._guild_id, self._user_id, self._yuan)
        await interaction.response.edit_message(
            content=f"💔 **{self._char['name']}** has been removed from your harem. **+¥{self._yuan:,}**",
            view=self,
        )
        guild  = self._bot.get_guild(self._guild_id)
        member = guild.get_member(self._user_id) if guild else None
        if guild and member:
            from cogs.achievements import unlock as unlock_achievement, check_milestone
            divorces = await self._bot.db.increment_counter(self._user_id, "gacha_divorces")
            await asyncio.gather(
                unlock_achievement(self._bot, guild, member, "first_divorce"),
                check_milestone(self._bot, guild, member, "gacha_divorces", divorces),
            )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self._user_id:
            await interaction.response.send_message("This isn't your divorce.", ephemeral=True)
            return
        self.stop()
        self._disable_all()
        await interaction.response.edit_message(content="Divorce cancelled.", view=self)


class GiftView(discord.ui.View):
    TIMEOUT = 300

    def __init__(self, db, guild_id: int, giver: discord.Member, target: discord.Member, char: dict):
        super().__init__(timeout=self.TIMEOUT)
        self._db       = db
        self._guild_id = guild_id
        self._giver    = giver
        self._target   = target
        self._char     = char
        self._settled  = False

    def _pending_embed(self) -> discord.Embed:
        char = self._char
        e = discord.Embed(
            title="Gift Incoming",
            description=(
                f"{self._giver.mention} wants to gift **{char['name']}** {stars(char['rarity'])}\n"
                f"to {self._target.mention}\n\n"
                f"{self._target.mention} · Decline within 5 minutes or the gift expires."
            ),
            color=FACTION_COLOR.get(char.get("faction"), 0xCC0000),
        )
        if img := pick_image(char):
            e.set_thumbnail(url=img)
        return e

    def _disable_all(self):
        for item in self.children:
            item.disabled = True

    async def on_timeout(self):
        if self._settled:
            return
        self._settled = True
        self._disable_all()
        char = self._char
        embed = discord.Embed(
            title="Gift Expired",
            description=f"{self._target.mention} didn't respond · **{char['name']}** was not sent.",
            color=0x888888,
        )
        if img := pick_image(char):
            embed.set_thumbnail(url=img)
        try:
            await self.message.edit(embed=embed, view=self)
        except Exception:
            pass

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self._target.id:
            await interaction.response.send_message("This gift isn't for you.", ephemeral=True)
            return
        if self._settled:
            await interaction.response.send_message("Already resolved.", ephemeral=True)
            return
        self._settled = True
        self.stop()
        self._disable_all()
        char = self._char
        ok = await self._db.gift_character(self._guild_id, self._giver.id, self._target.id, char["id"])
        if ok:
            from .cache import set_owner
            await set_owner(self._guild_id, char["id"], self._target.id)
            embed = discord.Embed(
                title="Gift Accepted",
                description=f"{self._target.mention} received **{char['name']}** from {self._giver.mention}.",
                color=FACTION_COLOR.get(char.get("faction"), 0xCC0000),
            )
        else:
            embed = discord.Embed(
                title="Gift Failed",
                description=f"{self._giver.mention} no longer owns **{char['name']}**.",
                color=0x888888,
            )
        if img := pick_image(char):
            embed.set_thumbnail(url=img)
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self._target.id:
            await interaction.response.send_message("This gift isn't for you.", ephemeral=True)
            return
        if self._settled:
            await interaction.response.send_message("Already resolved.", ephemeral=True)
            return
        self._settled = True
        self.stop()
        self._disable_all()
        char = self._char
        embed = discord.Embed(
            title="Gift Declined",
            description=f"{self._target.mention} declined **{char['name']}** from {self._giver.mention}.",
            color=0x888888,
        )
        if img := pick_image(char):
            embed.set_thumbnail(url=img)
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass
        await interaction.edit_original_response(embed=embed, view=self)


class CharacterSelectView(discord.ui.View):
    def __init__(self, candidates: list[dict], on_pick, author_id: int, timeout: int = 60):
        super().__init__(timeout=timeout)
        self._on_pick   = on_pick
        self._author_id = author_id
        self._chars     = {ch["id"]: ch for ch in candidates}
        options = [
            discord.SelectOption(
                label=ch["name"][:100],
                description=f"{ch['rarity']} · {ch.get('faction') or 'Unknown'}",
                value=ch["id"],
            )
            for ch in candidates[:25]
        ]
        sel = discord.ui.Select(placeholder="Choose a character...", options=options)
        sel.callback = self._handle
        self.add_item(sel)

    async def _handle(self, interaction: discord.Interaction):
        if interaction.user.id != self._author_id:
            await interaction.response.send_message("This isn't your selection.", ephemeral=True)
            return
        char = self._chars[interaction.data["values"][0]]
        await interaction.response.defer()
        self.stop()
        try:
            await self._on_pick(char)
        except discord.HTTPException:
            pass


async def show_char_picker(send_fn, candidates: list[dict], author_id: int, on_pick) -> None:
    lines = "\n".join(
        f"· **{c['name']}** — {c['rarity']} · {c.get('faction') or 'Unknown'}"
        for c in candidates[:25]
    )
    embed = discord.Embed(color=0xCC0000, title="Multiple matches found", description=lines)
    embed.set_footer(text=f"Don't see your favorite figure? Submit them at {SUBMIT_URL}")
    await send_fn(embed=embed, view=CharacterSelectView(candidates[:25], on_pick, author_id))
