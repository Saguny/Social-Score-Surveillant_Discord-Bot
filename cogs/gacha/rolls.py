import asyncio
import random

import discord
from config.personalities import RARITY_WEIGHT
from cogs.achievements import unlock as unlock_achievement

from . import cache, characters
from .constants import (
    BASE_ROLLS, MAX_STREAK_BONUS,
    ROLL_BONUS_PER_TIER, WISHLIST_MAX, WISHLIST_SLOT_TIERS,
    WISHLIST_SPAWN_BASE, WISHLIST_SPAWN_RATES,
)
from .embeds import roll_embed, pick_image, stars
from .views import DupeYuanView


def roll_weighted(
    gender: str | None = None,
    wishlist_ids: list[str] | None = None,
    wishlist_boost: float = 0.0,
) -> tuple[str, dict]:
    chars = characters.all_chars()
    if gender:
        pool = {k: v for k, v in chars.items() if v.get("gender") == gender} or chars
    else:
        pool = chars
    keys         = list(pool.keys())
    wishlist_set = set(wishlist_ids or [])
    weights      = [
        RARITY_WEIGHT.get(pool[k]["rarity"], 60) + (wishlist_boost if k in wishlist_set else 0.0)
        for k in keys
    ]
    cid = random.choices(keys, weights=weights)[0]
    return cid, pool[cid]


async def max_rolls(guild_id: int, user_id: int, db) -> int:
    streak, roll_tier = await asyncio.gather(
        db.get_counter(user_id, "topgg_vote_streak:current"),
        db.get_counter(user_id, f"gacha:upgrade:{guild_id}:roll_bonus"),
    )
    roll_tier = int(roll_tier or 0)
    bonus     = ROLL_BONUS_PER_TIER[roll_tier - 1] if roll_tier > 0 else 0
    return BASE_ROLLS + min(int(streak or 0), MAX_STREAK_BONUS) + bonus


async def wishlist_max_slots(guild_id: int, user_id: int, db) -> int:
    tier = int(await db.get_counter(user_id, f"gacha:upgrade:{guild_id}:wishlist_slots") or 0)
    return WISHLIST_SLOT_TIERS[tier - 1] if tier > 0 else WISHLIST_MAX


async def do_roll(
    bot,
    db,
    guild_id: int,
    user_id: int,
    display_name: str,
    send_fn,
    gender: str | None = None,
) -> None:
    max_r, (rolls_used, ttl) = await asyncio.gather(
        max_rolls(guild_id, user_id, db),
        cache.get_roll_state(guild_id, user_id),
    )

    if rolls_used >= max_r:
        if await cache.set_rate_limit_warned(guild_id, user_id):
            mins      = max(1, (ttl + 59) // 60)
            streak    = await db.get_counter(user_id, "topgg_vote_streak:current") or 0
            roll_tier = await db.get_counter(user_id, f"gacha:upgrade:{guild_id}:roll_bonus") or 0
            notes     = []
            if (vb := min(int(streak), MAX_STREAK_BONUS)):
                notes.append(f"+{vb} vote streak")
            if roll_tier and (sb := ROLL_BONUS_PER_TIER[int(roll_tier) - 1]):
                notes.append(f"+{sb} upgrade")
            limit_note = f" ({', '.join(notes)})" if notes else ""
            await send_fn(
                f"**{display_name}**, the roulette is limited to "
                f"**{max_r}** uses per hour{limit_note}. **{mins} min** left.\n"
                f"Vote to reset your rolls and increase your limit: `ccp vote`"
            )
        return

    wishlist_ids, spawn_tier = await asyncio.gather(
        db.get_wishlist(guild_id, user_id),
        db.get_counter(user_id, f"gacha:upgrade:{guild_id}:wishlist_spawn"),
    )
    spawn_tier     = int(spawn_tier or 0)
    spawn_rate     = WISHLIST_SPAWN_RATES[spawn_tier - 1] if spawn_tier > 0 else WISHLIST_SPAWN_BASE
    wishlist_boost = spawn_rate * 100  # convert 0.02–0.05 → 2.0–5.0 weight units per wishlisted char

    char_id, char = roll_weighted(gender, wishlist_ids=wishlist_ids or None, wishlist_boost=wishlist_boost)

    image_url = pick_image(char)
    new_count, owner_id = await asyncio.gather(
        cache.increment_rolls(guild_id, user_id),
        cache.get_owner(guild_id, char_id, db),
    )
    rolls_remaining = max_r - new_count
    dupe = owner_id is not None

    owner_name: str | None = None
    if dupe:
        guild_obj = bot.get_guild(guild_id)
        member    = guild_obj.get_member(owner_id) if guild_obj else None
        if member:
            owner_name = member.display_name
        else:
            try:
                owner_name = (await bot.fetch_user(owner_id)).display_name
            except Exception:
                pass

    embed    = roll_embed(char, image_url, rolls_remaining, max_r, dupe=dupe, owner_name=owner_name)
    buy_view = DupeYuanView(char, guild_id, user_id) if dupe else None
    try:
        msg = await send_fn(embed=embed, **{"view": buy_view} if buy_view is not None else {})
    except discord.HTTPException:
        await cache.decrement_rolls(guild_id, user_id)
        return

    await cache.store_pending(msg.id, {
        "char_id":   char_id,
        "guild_id":  guild_id,
        "image_url": image_url or "",
        "dupe":      dupe,
    })

    if buy_view is not None:
        buy_view.message_id = msg.id

    guild  = bot.get_guild(guild_id)
    member = guild.get_member(user_id) if guild else None
    if guild and member:
        await unlock_achievement(bot, guild, member, "first_roll")

    if not dupe and guild and (jump_url := getattr(msg, "jump_url", None)):
        for watcher_id in await db.get_wishlist_watchers(guild_id, char_id):
            if watcher_id == user_id:
                continue
            try:
                w = guild.get_member(watcher_id) or await bot.fetch_user(watcher_id)
                await w.send(
                    f"**{char['name']}** {stars(char['rarity'])} from your wishlist just appeared in **{guild.name}**!\n"
                    f"{jump_url}"
                )
            except (discord.Forbidden, discord.HTTPException):
                pass
