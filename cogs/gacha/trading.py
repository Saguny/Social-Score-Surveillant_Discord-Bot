import discord

from . import characters
from .constants import SUBMIT_URL
from .search import find_all
from .views import GiftView, show_char_picker


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
                lambda c: _start_gift(guild_id, giver, target, c, send_fn, db),
            )
            return
        char = candidates[0]

    await _start_gift(guild_id, giver, target, char, send_fn, db)


async def _start_gift(guild_id, giver, target, char, send_fn, db) -> None:
    char_id = char.get("id", "")
    owned = await db.get_character_owner(guild_id, char_id)
    if owned != giver.id:
        await send_fn(f"You don't own **{char['name']}**.")
        return

    view = GiftView(db, guild_id, giver, target, char)
    msg  = await send_fn(content=target.mention, embed=view._pending_embed(), view=view)
    view.message = msg
