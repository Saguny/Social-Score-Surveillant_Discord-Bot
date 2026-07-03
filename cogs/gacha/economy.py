import discord

from config.shop import SHOP_ITEMS, GACHA_UPGRADE_TIERS


async def build_upgrades_embed(guild_id: int, user_id: int, db) -> discord.Embed:
    icons     = {"gacha_slots": "📋", "gacha_rolls": "🎰", "gacha_spawn": "🎯"}
    max_tiers = 4
    embed     = discord.Embed(title="Waifu Bureau · Upgrades", color=0x576F72)

    for item_id, meta in GACHA_UPGRADE_TIERS.items():
        tier   = int(await db.get_counter(user_id, f"gacha:upgrade:{guild_id}:{meta['key']}") or 0)
        label  = SHOP_ITEMS[item_id]["name"]
        costs  = meta["costs"]
        values = meta["values"]
        unit   = meta["unit"]

        if tier >= max_tiers:
            status = f"Tier {tier}/{max_tiers} · **MAXED** · {values[tier - 1]} {unit}"
        else:
            if tier > 0:
                current = values[tier - 1]
            else:
                current = "10" if item_id == "gacha_slots" else ("0" if item_id == "gacha_rolls" else "6.0")
            status = f"Tier {tier}/{max_tiers} · {current} {unit} -> {values[tier]} {unit} · ¥{costs[tier]:,}"

        embed.add_field(
            name=f"{icons[item_id]} {label}",
            value=f"{status}\n`/buy {item_id}`",
            inline=False,
        )

    return embed
