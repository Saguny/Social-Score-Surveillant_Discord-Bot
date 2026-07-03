import asyncio
import urllib.parse

import aiohttp
import discord

from . import cache, characters
from . import claims as _claims
from . import collection as _collection
from . import economy as _economy
from . import rolls as _rolls
from . import trading as _trading
from . import wishlist as _wishlist
from .constants import FACTION_COLOR, FACTION_LABEL, SUBMIT_URL
from .embeds import image_embed, pick_image, stars
from .search import find_all
from .views import ImageChoiceView, ImageView, show_char_picker


class GachaService:
    def __init__(self, bot):
        self.bot = bot
        self.db  = bot.db

    # roll

    async def roll(self, guild_id, user_id, display_name, send_fn, gender=None):
        await _rolls.do_roll(self.bot, self.db, guild_id, user_id, display_name, send_fn, gender)

    async def max_rolls(self, user_id: int) -> int:
        return await _rolls.max_rolls(user_id, self.db)

    async def wishlist_max_slots(self, user_id: int) -> int:
        return await _rolls.wishlist_max_slots(user_id, self.db)

    # claims

    async def process_claim(self, payload):
        await _claims.process_claim(self.bot, payload)

    # collection

    async def show_collection(self, guild_id, user, send_fn):
        await _collection.show_collection(guild_id, user, send_fn, self.db, self.bot)

    async def do_harem_image(self, guild_id, user, send_fn):
        await _collection.do_harem_image(guild_id, user, send_fn, self.db, self.bot)

    async def do_choose(self, guild_id, user, name, send_fn):
        await _collection.do_choose(guild_id, user, name, send_fn, self.db)

    async def show_top(self, send_fn):
        await _collection.show_top(send_fn, self.db)

    # wishlist

    async def view_wishlist(self, guild_id, target, send_fn):
        await _wishlist.view_wishlist(guild_id, target, send_fn, self.db)

    # trading

    async def do_gift(self, guild_id, giver, target, name, send_fn):
        await _trading.do_gift(guild_id, giver, target, name, send_fn, self.db)

    # image card

    async def build_card(self, char_id: str, char: dict):
        urls = char.get("image_urls") or []
        if not urls:
            return None, None
        rank_info = await self.db.get_character_rank(char_id)
        rank_text = (
            f"Global #{rank_info['rank']}  ·  {rank_info['claims']} claims"
            if rank_info["rank"] else "Unclaimed globally"
        )
        if len(urls) == 1:
            return image_embed(char, urls[0], 0, len(urls), rank_text), None
        view = ImageView(char, urls, rank_text)
        return view.build_embed(), view

    async def show_card(self, name: str, send_fn):
        char = characters.get(name)
        if not char:
            matches = find_all(name)
            if len(matches) > 1:
                view = ImageChoiceView(self, matches)
                await send_fn(
                    f"Multiple waifus match **{name}** — pick one:\n"
                    f"Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>",
                    view=view,
                )
                return
            char = matches[0] if matches else None
        else:
            char = {"id": name, **char}

        if not char:
            await send_fn(f"No waifu found matching **{name}**.\nDon't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
            return

        char_id    = char.get("id", name)
        embed, view = await self.build_card(char_id, char)
        if embed is None:
            await send_fn(f"No image available for **{char['name']}**.")
            return
        await send_fn(embed=embed, view=view) if view else await send_fn(embed=embed)

    # whois

    async def do_whois(self, send_fn, name: str, author_id: int = 0):
        char = characters.get(name)
        if not char:
            candidates = find_all(name)
            if not candidates:
                await send_fn(f"No waifu found matching **{name}**. Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>")
                return
            if len(candidates) > 1:
                await show_char_picker(send_fn, candidates, author_id, lambda c: self.do_whois(send_fn, c["id"], author_id))
                return
            char = candidates[0]

        wiki      = char.get("wiki") or char.get("id", name)
        faction   = FACTION_LABEL.get(char["faction"], char["faction"].upper())
        color     = FACTION_COLOR.get(char["faction"], 0xCC0000)
        image_url = pick_image(char)

        extract = None
        try:
            url = f"https://en.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(wiki)}"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    headers={"User-Agent": "SocialCreditBot/2.0"},
                    timeout=aiohttp.ClientTimeout(total=8),
                ) as resp:
                    if resp.status == 200:
                        data    = await resp.json()
                        extract = data.get("extract", "")
                        if extract and len(extract) > 400:
                            extract = extract[:400].rsplit(" ", 1)[0] + "…"
        except Exception:
            pass

        embed = discord.Embed(
            title=char["name"],
            description=extract or char.get("title", "No description available."),
            color=color,
        )
        s = char.get("stats", {})
        embed.add_field(name="FACTION",   value=faction,                     inline=True)
        embed.add_field(name="RARITY",    value=stars(char["rarity"]),        inline=True)
        embed.add_field(name="AUTHORITY", value=str(s.get("authority", "?")), inline=False)
        embed.add_field(name="MILITARY",  value=str(s.get("military",  "?")), inline=False)
        embed.add_field(name="CHARISMA",  value=str(s.get("charisma",  "?")), inline=False)
        if wiki:
            embed.add_field(
                name="WIKIPEDIA",
                value=f"[{char['name']}](https://en.wikipedia.org/wiki/{urllib.parse.quote(wiki)})",
                inline=True,
            )
        if image_url:
            embed.set_thumbnail(url=image_url)
        embed.timestamp = discord.utils.utcnow()
        await send_fn(embed=embed)

    # economy / upgrades 

    async def upgrades_embed(self, user_id: int) -> discord.Embed:
        return await _economy.build_upgrades_embed(user_id, self.db)

    # char cache managemen

    async def reload_chars(self) -> int:
        all_chars = await self.db.get_all_characters()
        chars_with_images = {cid: ch for cid, ch in all_chars.items() if ch.get("image_urls")}
        characters.load(chars_with_images)
        return len(chars_with_images)
