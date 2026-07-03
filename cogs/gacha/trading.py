import discord

from . import characters
from .constants import FACTION_COLOR, SUBMIT_URL
from .embeds import stars, pick_image
from .search import find_all
from .views import show_char_picker


async def do_gift(
    guild_id: int,
    giver: discord.Member | discord.User,
    target: discord.Member | discord.User,
    name: str,
    send_fn,
    db,
) -> None:
    char = characters.get(name)
    if not char:
        candidates = find_all(name)
        if not candidates:
            await send_fn(
                f"No waifu found matching **{name}**.\n"
                f"Don't see your favorite figure? Submit them for review: <{SUBMIT_URL}>"
            )
            return
        if len(candidates) > 1:
            await show_char_picker(
                send_fn, candidates, giver.id,
                lambda c: _finish_gift(guild_id, giver, target, c, send_fn, db),
            )
            return
        char = candidates[0]

    await _finish_gift(guild_id, giver, target, char, send_fn, db)


async def _finish_gift(guild_id, giver, target, char, send_fn, db) -> None:
    char_id = char.get("id", "")
    ok = await db.gift_character(guild_id, giver.id, target.id, char_id)
    if not ok:
        await send_fn(f"You don't own **{char['name']}**.")
        return
    embed = discord.Embed(
        title="Waifu Gifted",
        description=(
            f"{giver.mention} gifted **{char['name']}** {stars(char['rarity'])}\n"
            f"to {target.mention}"
        ),
        color=FACTION_COLOR.get(char["faction"], 0xCC0000),
    )
    if img := pick_image(char):
        embed.set_thumbnail(url=img)
    await send_fn(embed=embed)
