import asyncio
import os
import random
import re

import discord
from discord import app_commands
from discord.ext import commands

from . import cache, characters
from .collection import filtered_chars
from .constants import DIVORCE_YUAN, FACTION_COLOR, FACTION_LABEL, FACTION_ORDER, RARITY_ORDER, SUBMIT_URL
from .search import figure_ac, find_all, find_one, owned_figure_ac, target_owned_figure_ac, wishlist_figure_ac
from .service import GachaService
from .views import BrowseView, DivorceConfirmView, TradeView, show_char_picker
from .embeds import pick_image, stars

_DASHBOARD_URL = os.getenv("DASHBOARD_URL", "https://off-by-one.digital/social-credit")


class GachaCog(commands.Cog, name="Gacha"):
    def __init__(self, bot: commands.Bot):
        self.bot     = bot
        self.service = GachaService(bot)

    async def cog_load(self):
        all_chars = await self.bot.db.get_all_characters()
        chars_with_images = {cid: ch for cid, ch in all_chars.items() if ch.get("image_urls")}
        characters.load(chars_with_images)
        print(f"[gacha] loaded {len(chars_with_images)}/{len(all_chars)} characters from DB (imageless excluded)")

    # ── roll commands ─────────────────────────────────────────────────────────

    @app_commands.command(name="roll", description="Roll for a random historical waifu")
    async def slash_roll(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.service.roll(interaction.guild.id, interaction.user.id, interaction.user.display_name, interaction.followup.send)

    @app_commands.command(name="rollwaifu", description="Roll for a female historical figure only")
    async def slash_rollwaifu(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.service.roll(interaction.guild.id, interaction.user.id, interaction.user.display_name, interaction.followup.send, gender="female")

    @app_commands.command(name="rollhusbando", description="Roll for a male historical figure only")
    async def slash_rollhusbando(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.service.roll(interaction.guild.id, interaction.user.id, interaction.user.display_name, interaction.followup.send, gender="male")

    @commands.command(name="roll", aliases=["r"])
    async def prefix_roll(self, ctx: commands.Context):
        async with ctx.typing():
            await self.service.roll(ctx.guild.id, ctx.author.id, ctx.author.display_name, ctx.send)

    @commands.command(name="rollwaifu", aliases=["rw"])
    async def prefix_rollwaifu(self, ctx: commands.Context):
        async with ctx.typing():
            await self.service.roll(ctx.guild.id, ctx.author.id, ctx.author.display_name, ctx.send, gender="female")

    @commands.command(name="rollhusbando", aliases=["rh"])
    async def prefix_rollhusbando(self, ctx: commands.Context):
        async with ctx.typing():
            await self.service.roll(ctx.guild.id, ctx.author.id, ctx.author.display_name, ctx.send, gender="male")

    # ── image / card ──────────────────────────────────────────────────────────

    @app_commands.command(name="image", description="View a personality's card")
    @app_commands.describe(name="Name of the historical waifu")
    @app_commands.autocomplete(name=figure_ac)
    async def slash_image(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        await self.service.show_card(name, interaction.followup.send, guild_id=interaction.guild.id)

    @commands.command(name="image", aliases=["im"])
    async def prefix_image(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await ctx.send("Usage: `ccp image <waifu name>`")
                return
            await self.service.show_card(name, ctx.send, guild_id=ctx.guild.id)

    # ── collection / harem ────────────────────────────────────────────────────

    @app_commands.command(name="harem", description="View your harem")
    @app_commands.describe(user="View another member's harem")
    async def slash_collection(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        await self.service.show_collection(interaction.guild.id, user or interaction.user, interaction.followup.send)

    @app_commands.command(name="haremimage", description="Browse your harem images one by one")
    @app_commands.describe(user="Browse another member's harem")
    async def slash_harem_image(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        await self.service.do_harem_image(interaction.guild.id, user or interaction.user, interaction.followup.send)

    @app_commands.command(name="choose", description="Set your featured harem thumbnail")
    @app_commands.describe(name="Name of the waifu to feature")
    async def slash_choose(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer(ephemeral=True)
        await self.service.do_choose(interaction.guild.id, interaction.user, name, interaction.followup.send)

    @commands.command(name="harem", aliases=["collection", "h"])
    async def prefix_collection(self, ctx: commands.Context, user: discord.Member = None):
        async with ctx.typing():
            await self.service.show_collection(ctx.guild.id, user or ctx.author, ctx.send)

    @commands.command(name="haremrank", aliases=["hr"])
    async def prefix_collection_rank(self, ctx: commands.Context, user: discord.Member = None):
        async with ctx.typing():
            await self.service.show_collection(ctx.guild.id, user or ctx.author, ctx.send)

    @commands.command(name="haremimage", aliases=["hi", "haremi"])
    async def prefix_harem_image(self, ctx: commands.Context, user: discord.Member = None):
        async with ctx.typing():
            await self.service.do_harem_image(ctx.guild.id, user or ctx.author, ctx.send)

    @commands.command(name="haremimagerank", aliases=["hir"])
    async def prefix_harem_image_rank(self, ctx: commands.Context, user: discord.Member = None):
        async with ctx.typing():
            await self.service.do_harem_image(ctx.guild.id, user or ctx.author, ctx.send)

    @commands.command(name="choose")
    async def prefix_choose(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await ctx.send("Usage: `ccp choose <waifu name>`")
                return
            await self.service.do_choose(ctx.guild.id, ctx.author, name, ctx.send)

    # ── browse ────────────────────────────────────────────────────────────────

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
        items = filtered_chars(faction, rarity)
        rows  = await self.bot.db.get_user_collection(interaction.guild.id, interaction.user.id)
        owned = {r["character_id"] for r in rows}
        view  = BrowseView(items, owned, faction, rarity)
        await interaction.followup.send(embed=view.build_embed(), view=view)

    # ── top ───────────────────────────────────────────────────────────────────

    @app_commands.command(name="top", description="Global leaderboard of most-claimed waifus")
    async def slash_top(self, interaction: discord.Interaction):
        await interaction.response.defer()
        await self.service.show_top(interaction.followup.send)

    @commands.command(name="top")
    async def prefix_top(self, ctx: commands.Context):
        async with ctx.typing():
            await self.service.show_top(ctx.send)

    # ── whois ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="whois", description="Look up a waifu's Wikipedia description")
    @app_commands.describe(name="Name of the waifu")
    @app_commands.autocomplete(name=figure_ac)
    async def slash_whois(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        await self.service.do_whois(interaction.followup.send, name, interaction.user.id)

    @commands.command(name="whois")
    async def prefix_whois(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await ctx.send("Usage: `ccp whois <name>`")
                return
            await self.service.do_whois(ctx.send, name, ctx.author.id)

    # ── trade ─────────────────────────────────────────────────────────────────

    @app_commands.command(name="trade", description="Offer a waifu trade to another member")
    @app_commands.describe(
        user="The member to trade with",
        offer="The waifu you're giving away",
        request="The waifu you want in return",
    )
    @app_commands.autocomplete(offer=owned_figure_ac, request=target_owned_figure_ac)
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

        offer_char   = characters.get(offer)   or find_one(offer)
        request_char = characters.get(request) or find_one(request)

        if not offer_char:
            await interaction.followup.send(f"No waifu found matching **{offer}**.\nDon't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return
        if not request_char:
            await interaction.followup.send(f"No waifu found matching **{request}**.\nDon't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return

        if "id" not in offer_char:
            offer_char = {**offer_char, "id": offer}
        if "id" not in request_char:
            request_char = {**request_char, "id": request}

        offer_id   = offer_char["id"]
        request_id = request_char["id"]
        guild_id   = interaction.guild.id

        if not await self.bot.db.has_character(guild_id, interaction.user.id, offer_id):
            await interaction.followup.send(f"You don't own **{offer_char['name']}**.")
            return
        if not await self.bot.db.has_character(guild_id, user.id, request_id):
            await interaction.followup.send(f"{user.display_name} doesn't own **{request_char['name']}**.")
            return

        embed = discord.Embed(
            title="Trade Offer",
            description=(
                f"{interaction.user.mention} offers **{offer_char['name']}** {stars(offer_char['rarity'])}\n"
                f"in exchange for **{request_char['name']}** {stars(request_char['rarity'])}\n\n"
                f"{user.mention}, do you accept?"
            ),
            color=FACTION_COLOR.get(offer_char["faction"], 0xCC0000),
        )
        if img := pick_image(offer_char):
            embed.set_thumbnail(url=img)

        await interaction.followup.send(embed=embed, view=TradeView(interaction.user, user, offer_id, request_id))

    # ── gift ──────────────────────────────────────────────────────────────────

    @app_commands.command(name="gift", description="Give one of your waifus to another member")
    @app_commands.describe(waifu="The waifu you want to give", user="Who to give it to")
    @app_commands.autocomplete(waifu=owned_figure_ac)
    async def slash_gift(self, interaction: discord.Interaction, waifu: str, user: discord.Member):
        await interaction.response.defer()
        if user.id == interaction.user.id:
            await interaction.followup.send("You can't gift to yourself.")
            return
        if user.bot:
            await interaction.followup.send("You can't gift to a bot.")
            return
        await self.service.do_gift(interaction.guild.id, interaction.user, user, waifu, interaction.followup.send)

    @commands.command(name="gift")
    async def prefix_gift(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
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
            name = re.sub(r"<@!?\d+>", "", name).strip()
            if not name:
                await ctx.send("Please provide a waifu name: `ccp gift <waifu> @user`")
                return
            await self.service.do_gift(ctx.guild.id, ctx.author, target, name, ctx.send)

    # ── wishlist ──────────────────────────────────────────────────────────────

    wishlist_group = app_commands.Group(name="wishlist", description="Manage your waifu wishlist")

    @wishlist_group.command(name="add", description="Add a waifu to your wishlist")
    @app_commands.describe(name="Waifu to wishlist")
    @app_commands.autocomplete(name=figure_ac)
    async def wishlist_add(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        char = characters.get(name) or find_one(name)
        if not char:
            await interaction.followup.send(f"No waifu found matching **{name}**.\nDon't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return
        char_id   = char.get("id", name)
        max_slots = await self.service.wishlist_max_slots(interaction.guild.id, interaction.user.id)
        result    = await self.bot.db.add_wishlist(interaction.guild.id, interaction.user.id, char_id, max_size=max_slots)
        if result == "added":
            await interaction.followup.send(f"Added **{char['name']}** {stars(char['rarity'])} to your wishlist.")
        elif result == "full":
            await interaction.followup.send(f"Your wishlist is full ({max_slots} max). Remove one first or upgrade with `/buy gacha_slots`.")
        else:
            await interaction.followup.send(f"**{char['name']}** is already on your wishlist.")

    @wishlist_group.command(name="remove", description="Remove a waifu from your wishlist")
    @app_commands.describe(name="Waifu to remove")
    @app_commands.autocomplete(name=wishlist_figure_ac)
    async def wishlist_remove(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        char = characters.get(name) or find_one(name)
        if not char:
            await interaction.followup.send(f"No waifu found matching **{name}**.\nDon't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return
        char_id = char.get("id", name)
        removed = await self.bot.db.remove_wishlist(interaction.guild.id, interaction.user.id, char_id)
        if removed:
            await interaction.followup.send(f"Removed **{char['name']}** from your wishlist.")
        else:
            await interaction.followup.send(f"**{char['name']}** wasn't on your wishlist.")

    @wishlist_group.command(name="view", description="View a wishlist")
    @app_commands.describe(user="View another member's wishlist")
    async def wishlist_view(self, interaction: discord.Interaction, user: discord.Member | None = None):
        await interaction.response.defer()
        await self.service.view_wishlist(interaction.guild.id, user or interaction.user, interaction.followup.send)

    @commands.command(name="wish")
    async def prefix_wish(self, ctx: commands.Context, *, name: str = ""):
        async with ctx.typing():
            if not name:
                await self.service.view_wishlist(ctx.guild.id, ctx.author, ctx.send)
                return
            max_slots = await self.service.wishlist_max_slots(ctx.guild.id, ctx.author.id)
            char      = characters.get(name)
            if not char:
                candidates = find_all(name)
                if not candidates:
                    await ctx.send(f"No waifu found matching **{name}**.")
                    await ctx.send(f"Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
                    return
                if len(candidates) > 1:
                    async def _wish_pick(c):
                        result = await self.bot.db.add_wishlist(ctx.guild.id, ctx.author.id, c["id"], max_size=max_slots)
                        if result == "added":
                            await ctx.send(f"Added **{c['name']}** {stars(c['rarity'])} to your wishlist.")
                        elif result == "full":
                            await ctx.send(f"Your wishlist is full ({max_slots} max). Remove one first or upgrade with `/buy gacha_slots`.")
                        else:
                            await ctx.send(f"**{c['name']}** is already on your wishlist.")
                    await show_char_picker(ctx.send, candidates, ctx.author.id, _wish_pick)
                    return
                char = candidates[0]
            char_id = char.get("id", name)
            result  = await self.bot.db.add_wishlist(ctx.guild.id, ctx.author.id, char_id, max_size=max_slots)
            if result == "added":
                await ctx.send(f"Added **{char['name']}** {stars(char['rarity'])} to your wishlist.")
            elif result == "full":
                await ctx.send(f"Your wishlist is full ({max_slots} max). Remove one first or upgrade with `/buy gacha_slots`.")
            else:
                await ctx.send(f"**{char['name']}** is already on your wishlist.")

    @commands.command(name="wl", aliases=["wishlist"])
    async def prefix_wl(self, ctx: commands.Context, *, args: str = ""):
        async with ctx.typing():
            parts = args.strip().split(None, 1)
            if parts and parts[0].lower() == "remove":
                name = parts[1] if len(parts) > 1 else ""
                if not name:
                    await ctx.send("Usage: `ccp wl remove <name>`")
                    return
                char = characters.get(name)
                if not char:
                    candidates = find_all(name)
                    if not candidates:
                        await ctx.send(f"No waifu found matching **{name}**.")
                        return
                    if len(candidates) > 1:
                        async def _remove_pick(c):
                            removed = await self.bot.db.remove_wishlist(ctx.guild.id, ctx.author.id, c["id"])
                            if removed:
                                await ctx.send(f"Removed **{c['name']}** from your wishlist.")
                            else:
                                await ctx.send(f"**{c['name']}** wasn't on your wishlist.")
                        await show_char_picker(ctx.send, candidates, ctx.author.id, _remove_pick)
                        return
                    char = candidates[0]
                char_id = char.get("id", name)
                removed = await self.bot.db.remove_wishlist(ctx.guild.id, ctx.author.id, char_id)
                if removed:
                    await ctx.send(f"Removed **{char['name']}** from your wishlist.")
                else:
                    await ctx.send(f"**{char['name']}** wasn't on your wishlist.")
            else:
                await self.service.view_wishlist(ctx.guild.id, ctx.author, ctx.send)

    # ── divorce ───────────────────────────────────────────────────────────────

    @app_commands.command(name="divorce", description="Remove a waifu from your harem")
    @app_commands.describe(name="Waifu to divorce")
    @app_commands.autocomplete(name=owned_figure_ac)
    async def slash_divorce(self, interaction: discord.Interaction, name: str):
        await interaction.response.defer()
        await self._do_divorce(interaction.guild.id, interaction.user.id, name, interaction.followup.send)

    @commands.command(name="divorce")
    async def prefix_divorce(self, ctx: commands.Context, *, name: str):
        async with ctx.typing():
            await self._do_divorce(ctx.guild.id, ctx.author.id, name, ctx.send)

    async def _do_divorce(self, guild_id: int, user_id: int, name: str, send_fn):
        char = characters.get(name)
        if not char:
            candidates = find_all(name)
            if not candidates:
                await send_fn(f"No waifu found matching **{name}**. Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
                return
            if len(candidates) > 1:
                await show_char_picker(send_fn, candidates, user_id, lambda c: self._do_divorce(guild_id, user_id, c["id"], send_fn))
                return
            char = candidates[0]
        char_id = char.get("id", name)
        if not await self.bot.db.has_character(guild_id, user_id, char_id):
            await send_fn(f"You don't have **{char['name']}** in your harem.")
            return
        lo, hi = DIVORCE_YUAN.get(char["rarity"], (25, 125))
        yuan   = random.randint(lo, hi)
        view   = DivorceConfirmView(self.bot, guild_id, user_id, char, yuan)
        await send_fn(
            f"Divorce **{char['name']}** {stars(char['rarity'])}?\n"
            f"You'll receive **¥{yuan:,}** · this cannot be undone.",
            view=view,
        )

    # ── cooldown ──────────────────────────────────────────────────────────────

    @commands.command(name="cooldown", aliases=["cd", "claim"])
    async def prefix_cooldown(self, ctx: commands.Context):
        async with ctx.typing():
            import time as _time
            from .constants import MAX_CLAIMS_PER_HOUR
            guild_id = ctx.guild.id
            user_id  = ctx.author.id

            max_r, roll_state, claim_state, voter_expiry = await asyncio.gather(
                self.service.max_rolls(guild_id, user_id),
                cache.get_roll_state(guild_id, user_id),
                cache.get_claim_state(guild_id, user_id),
                self.bot.db.get_voter_badge_expiry(user_id),
            )
            rolls_used, roll_ttl   = roll_state
            claims_used, claim_ttl = claim_state

            if claims_used >= MAX_CLAIMS_PER_HOUR and claim_ttl > 0:
                mins       = max(1, (claim_ttl + 59) // 60)
                claim_line = f"Your next claim is available in **{mins}min**"
            else:
                claim_line = "You can claim **now**"

            rolls_left = max(0, max_r - rolls_used)
            if rolls_left > 0:
                roll_line = f"You have **{rolls_left}/{max_r}** rolls remaining"
            else:
                mins      = max(1, (roll_ttl + 59) // 60)
                roll_line = f"Your rolls reset in **{mins}min**"

            now = int(_time.time())
            if voter_expiry and voter_expiry > now:
                vote_line = f"Vote available <t:{voter_expiry}:R> (<t:{voter_expiry}:f>)"
            else:
                vote_line = "You may vote right now! `ccp vote`"

            await ctx.send(f"{claim_line}\n{roll_line}\n{vote_line}")

    # ── suggestions ───────────────────────────────────────────────────────────

    @app_commands.command(name="suggestions", description="Suggest a new character for the gacha pool")
    async def slash_suggest(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="Suggest a Character",
            description=(
                "Think a real historical figure or public personality deserves a spot in the Waifu Bureau? "
                "Submit them for community review!\n\n"
                f"-> **[Open Community Wishlist]({_DASHBOARD_URL}/wishlist)**\n"
                f"-> **[Submit a Suggestion]({_DASHBOARD_URL}/submit)**\n\n"
                "Submissions with the most votes go to the top of the admin queue. "
                "If your suggestion is approved, your name appears as **Suggested by @you** on every card."
            ),
            color=0x576F72,
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Suggest a Character", style=discord.ButtonStyle.link, url=f"{_DASHBOARD_URL}/submit"))
        view.add_item(discord.ui.Button(label="View Wishlist",       style=discord.ButtonStyle.link, url=f"{_DASHBOARD_URL}/wishlist"))
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @commands.command(name="suggestions")
    async def prefix_suggest(self, ctx: commands.Context):
        async with ctx.typing():
            embed = discord.Embed(
                title="Suggest a Character",
                description=(
                    f"Submit a real historical figure for the gacha pool at **{_DASHBOARD_URL}/submit**\n"
                    f"View community requests at **{_DASHBOARD_URL}/wishlist**\n\n"
                    "Approved submissions credit you as **Suggested by @you** on every card."
                ),
                color=0x576F72,
            )
            await ctx.send(embed=embed)

    # ── upgrades ──────────────────────────────────────────────────────────────

    @commands.command(name="upgrades")
    async def prefix_upgrades(self, ctx: commands.Context):
        async with ctx.typing():
            embed = await self.service.upgrades_embed(ctx.guild.id, ctx.author.id)
            await ctx.send(embed=embed)

    # ── owner util ────────────────────────────────────────────────────────────

    @commands.command(name="reloadchars")
    @commands.is_owner()
    async def prefix_reload_chars(self, ctx: commands.Context):
        async with ctx.typing():
            n = await self.service.reload_chars()
            await ctx.send(f"Reloaded {n} characters from DB.")

    # ── claim listener ────────────────────────────────────────────────────────

    @commands.Cog.listener("on_raw_reaction_add")
    async def on_claim(self, payload: discord.RawReactionActionEvent):
        await self.service.process_claim(payload)
