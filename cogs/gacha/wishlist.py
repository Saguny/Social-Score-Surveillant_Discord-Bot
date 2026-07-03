import discord

from . import characters
from .embeds import stars


async def view_wishlist(
    guild_id: int,
    target: discord.Member | discord.User,
    send_fn,
    db,
) -> None:
    ids  = await db.get_wishlist(guild_id, target.id)
    name = target.display_name if hasattr(target, "display_name") else str(target)
    if not ids:
        await send_fn(f"**{name}** has no waifus on their wishlist.")
        return

    rows  = await db.get_user_collection(guild_id, target.id)
    owned = {r["character_id"] for r in rows}
    lines = []
    for char_id in ids:
        char = characters.get(char_id)
        if not char:
            continue
        check = "✓" if char_id in owned else "·"
        lines.append(f"`{check}` {stars(char['rarity'])} **{char['name']}** — {char['title']}")

    embed = discord.Embed(
        title=f"{name}'s Wishlist",
        description="\n".join(lines) or "Empty.",
        color=0xCC0000,
    )
    embed.set_footer(text="✓ = already owned")
    await send_fn(embed=embed)
