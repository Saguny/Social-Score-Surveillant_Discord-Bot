import time
import discord
from discord import app_commands
from discord.ext import commands
from config.shop import SHOP_ITEMS


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="shop", description="Browse the Social Credit Bureau's shop")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 人民商店")
        for item_id, item in SHOP_ITEMS.items():
            embed.add_field(
                name=f"{item['name']}  ·  ¥{item['cost']}",
                value=f"`{item_id}` · {item['description']}",
                inline=False,
            )
        embed.set_footer(text="GLORY TO THE CCP!")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="yuan", description="Check your Yuan balance")
    async def yuan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await self.db.get_user(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
        embed.add_field(name="CITIZEN", value=str(interaction.user), inline=False)
        embed.add_field(name="BALANCE", value=f"¥{user['yuan']}", inline=True)
        embed.add_field(name="TOTAL EARNED", value=f"¥{user['total_yuan_earned']}", inline=True)
        embed.add_field(name="TOTAL SPENT", value=f"¥{user['total_yuan_spent']}", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="buy", description="Purchase an item from the shop")
    @app_commands.describe(
        item="Item ID (see /shop)",
        target="Target citizen (required for some items)",
        text="Denouncement text (required for denounce)",
    )
    async def buy(
        self,
        interaction: discord.Interaction,
        item: str,
        target: discord.Member = None,
        text: str = None,
    ):
        if item not in SHOP_ITEMS:
            await interaction.response.send_message(
                "Unknown item. Use `/shop` to see available items.", ephemeral=True
            )
            return

        cfg = SHOP_ITEMS[item]
        gid = interaction.guild.id
        uid = interaction.user.id

        if cfg["requires_target"] and target is None:
            await interaction.response.send_message("This item requires a target citizen.", ephemeral=True)
            return
        if cfg.get("requires_text") and not text:
            await interaction.response.send_message("This item requires a text argument.", ephemeral=True)
            return
        if target and (target.bot or target.id == uid):
            await interaction.response.send_message("Invalid target.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        cost = cfg["cost"]
        if item == "rehabilitate":
            rehab_count = await self.db.get_rehabilitation_count(gid, uid)
            cost = cfg["cost"] * (2 ** rehab_count)

        if not await self.db.spend_yuan(gid, uid, cost):
            balance = (await self.db.get_user(gid, uid))["yuan"]
            await interaction.followup.send(
                f"Insufficient funds. Balance: ¥{balance} · Cost: ¥{cost}", ephemeral=True
            )
            return

        await self.db.log_transaction(gid, uid, item, cost, target.id if target else None)
        await self.db.increment_items_bought(gid, uid)
        await self._dispatch(interaction, item, cfg, target, text, cost)

    async def _dispatch(self, interaction, item_id, cfg, target, text, cost):
        gid = interaction.guild.id
        uid = interaction.user.id

        if item_id == "report":
            await self.db.update_score(gid, target.id, -2.0, "official citizen report")
            await self.db.increment_reported(gid, target.id)
            await self.db.increment_filed_reports(gid, uid)
            report_num = await self.db.increment_report_counter(gid)

            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="OFFICIAL REPORT FILED", value=target.mention, inline=False)
            embed.add_field(name="SCORE IMPACT", value="−2.0", inline=True)
            embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "denounce":
            report_num = await self.db.increment_report_counter(gid)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公开谴责")
            embed.add_field(name="SUBJECT", value=target.mention, inline=False)
            embed.add_field(name="STATED CRIME", value=text[:100], inline=False)
            embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "surveillance":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "surveillance", expires_at, {"target_id": target.id})
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="SURVEILLANCE ACTIVE",
                value=f"Monitoring {target.mention} for 24 hours.\nScore changes will be reported to your inbox.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "rehabilitate":
            old, new = await self.db.update_score(gid, uid, 3.0, "rehabilitation certificate")
            embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
            embed.add_field(
                name="REHABILITATION APPROVED",
                value=f"Score adjusted: {old:.2f} -> {new:.2f}",
                inline=False,
            )
            embed.set_footer(text="GLORY TO THE CCP!")
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "expunge":
            await self.db.expunge_history(gid, uid, 5)
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="RECORDS EXPUNGED",
                value="Your last 5 score entries have been redacted from public record.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "freeze":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "freeze", expires_at)
            self.db.invalidate_effect_cache(gid, uid, "freeze")
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="SCORE FREEZE ACTIVE",
                value="Your social credit score is frozen for 1 hour.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "propaganda":
            embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 国家公告")
            embed.add_field(
                name="STATE COMMENDATION",
                value=(
                    f"The bureau formally commends citizen {interaction.user.mention} "
                    f"for their outstanding contributions to social harmony and the collective good."
                ),
                inline=False,
            )
            embed.set_footer(text="GLORY TO THE CCP!")
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="confess", description="Publicly confess your crimes to the Bureau for a score reprieve")
    @app_commands.describe(text="Your confession (max 200 characters)")
    async def confess(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id

        if len(text) > 200:
            await interaction.followup.send("Confession exceeds 200 characters.", ephemeral=True)
            return

        user = await self.db.get_user(gid, uid)
        cost = max(200, int((750.0 - user["score"]) * 5))

        if not await self.db.spend_yuan(gid, uid, cost):
            await interaction.followup.send(
                f"Insufficient funds. Confession costs ¥{cost} at your current score. Balance: ¥{user['yuan']}",
                ephemeral=True,
            )
            return

        await self.db.log_transaction(gid, uid, "confess", cost)
        old, new = await self.db.update_score(gid, uid, 0.5, "public confession")

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公开认罪")
        embed.add_field(name="CITIZEN", value=interaction.user.mention, inline=False)
        embed.add_field(name="CONFESSION", value=text[:200], inline=False)
        embed.add_field(name="COST", value=f"¥{cost}", inline=True)
        embed.add_field(name="SCORE ADJUSTMENT", value=f"{old:.2f} -> {new:.2f}", inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    @buy.autocomplete("item")
    async def item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=f"{v['name']} (¥{v['cost']})", value=k)
            for k, v in SHOP_ITEMS.items()
            if current.lower() in k or current.lower() in v["name"].lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
