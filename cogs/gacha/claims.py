import asyncio

import discord
from cogs.achievements import unlock as unlock_achievement, check_milestone

from . import cache, characters
from .constants import DUPE_YUAN, MAX_CLAIMS_PER_HOUR
from .embeds import claimed_embed, stars


async def process_claim(bot, payload: discord.RawReactionActionEvent) -> None:
    if payload.user_id == bot.user.id or not payload.guild_id:
        return

    data, ttl = await cache.pop_pending(payload.message_id)
    if data is None:
        return

    guild_id  = data["guild_id"]
    char_id   = data["char_id"]
    image_url = data.get("image_url") or None
    is_dupe   = data.get("dupe", False)

    claims_used = await cache.increment_claims(guild_id, payload.user_id)
    if claims_used > MAX_CLAIMS_PER_HOUR:
        await cache.decrement_claims(guild_id, payload.user_id)
        await cache.store_pending(payload.message_id, data)
        try:
            channel  = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
            _, claim_ttl = await cache.get_claim_state(guild_id, payload.user_id)
            mins     = max(1, (claim_ttl + 59) // 60)
            await channel.send(
                f"<@{payload.user_id}> You've already claimed your character for this hour. **{mins} min** left.",
                delete_after=10,
            )
        except (discord.NotFound, discord.HTTPException):
            pass
        return

    char = characters.get(char_id)
    if not char:
        return

    claimer_id   = payload.user_id
    guild        = bot.get_guild(guild_id)
    claimer      = guild.get_member(claimer_id) if guild else None
    if claimer is None:
        try:
            claimer = await bot.fetch_user(claimer_id)
        except Exception:
            return
    claimer_name = claimer.display_name if hasattr(claimer, "display_name") else str(claimer)

    if is_dupe:
        yuan = DUPE_YUAN.get(char["rarity"], 100)
        await bot.db.adjust_yuan(guild_id, claimer_id, yuan)
        try:
            channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
            await channel.send(
                f"**{claimer_name}** +¥{yuan:,}",
                reference=discord.MessageReference(
                    message_id=payload.message_id,
                    channel_id=payload.channel_id,
                    fail_if_not_exists=False,
                ),
            )
        except (discord.NotFound, discord.HTTPException):
            pass
        if guild and isinstance(claimer, discord.Member):
            await unlock_achievement(bot, guild, claimer, "first_dupe")
        return

    claimed, _ = await asyncio.gather(
        bot.db.claim_character(guild_id, claimer_id, char_id),
        cache.set_owner(guild_id, char_id, claimer_id),
    )
    if not claimed:
        return

    rank_info = await bot.db.get_character_rank(char_id)

    try:
        channel = bot.get_channel(payload.channel_id) or await bot.fetch_channel(payload.channel_id)
        message = await channel.fetch_message(payload.message_id)
        await message.edit(embed=claimed_embed(char, image_url, claimer_name, rank_info["rank"]))
        await channel.send(f"**{claimer_name}** and **{char['name']}** are now married ❤️")
    except (discord.NotFound, discord.HTTPException):
        pass

    if guild and isinstance(claimer, discord.Member):
        wishlist = await bot.db.get_wishlist(guild_id, claimer_id)
        total    = await bot.db.increment_counter(claimer_id, "gacha_claims_total")
        await asyncio.gather(
            unlock_achievement(bot, guild, claimer, "first_claim"),
            check_milestone(bot, guild, claimer, "gacha_claims_total", total),
            *(
                [unlock_achievement(bot, guild, claimer, "claimed_legendary")]
                if char.get("rarity") == "legendary" else []
            ),
            *(
                [unlock_achievement(bot, guild, claimer, "wishlist_fulfilled"),
                 bot.db.remove_wishlist(guild_id, claimer_id, char_id)]
                if char_id in wishlist else []
            ),
        )

    for watcher_id in await bot.db.get_wishlist_watchers(guild_id, char_id):
        if watcher_id == claimer_id:
            continue
        try:
            watcher = (guild.get_member(watcher_id) if guild else None) or await bot.fetch_user(watcher_id)
            await watcher.send(
                f"**{char['name']}** {stars(char['rarity'])} from your wishlist was just claimed by "
                f"**{claimer_name}** in **{guild.name if guild else 'a server'}**!"
            )
        except (discord.Forbidden, discord.HTTPException):
            pass
