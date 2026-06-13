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
            bribed = await self.db.consume_effect(gid, target.id, "bribe")
            if bribed:
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
                embed.add_field(
                    name="REPORT NULLIFIED",
                    value=f"{target.mention} had a pending bribe. Your report was silently discarded.",
                    inline=False,
                )
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

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
            await self.db.update_score(gid, target.id, -20.0, "public denouncement")
            await self.db.increment_reported(gid, target.id)
            report_num = await self.db.increment_report_counter(gid)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公开谴责")
            embed.add_field(name="SUBJECT", value=target.mention, inline=False)
            embed.add_field(name="STATED CRIME", value=text[:100], inline=False)
            embed.add_field(name="SCORE IMPACT", value="−20.0", inline=True)
            embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "surveillance":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "surveillance", expires_at, {"target_id": target.id})
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="INTELLIGENCE PACKAGE ACQUIRED",
                value=f"Dossier on {target.mention} is ready.\nUse `/surveillance_report` within 30 days to redeem your one-time report.",
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
                value="Your social credit score is frozen for 2 hours.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "bribe":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "bribe", expires_at)
            embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
            embed.add_field(
                name="BRIBE ACCEPTED",
                value="The bureau has noted your generosity. The next report filed against you within 24 hours will be silently discarded.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "gulag":
            if await self.db.get_effect(gid, target.id, "freeze"):
                await interaction.followup.send(
                    f"{target.mention} is already score-frozen.", ephemeral=True
                )
                return
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, target.id, "freeze", expires_at)
            self.db.invalidate_effect_cache(gid, target.id, "freeze")
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 劳改营")
            embed.add_field(
                name="GULAG SENTENCE ISSUED",
                value=f"{target.mention}'s social credit score is frozen for 2 hours by order of the bureau.",
                inline=False,
            )
            await interaction.followup.send(embed=embed)

    @app_commands.command(name="surveillance_report", description="Redeem your surveillance package for a full 30-day intelligence dossier")
    @app_commands.describe(target="The citizen to pull the dossier on")
    async def surveillance_report(self, interaction: discord.Interaction, target: discord.Member):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = interaction.user.id

        if target.bot or target.id == uid:
            await interaction.followup.send("Invalid target.", ephemeral=True)
            return

        consumed = await self.db.consume_surveillance_for_target(gid, uid, target.id)
        if not consumed:
            await interaction.followup.send(
                "No active surveillance package on file for this citizen. Purchase one via `/buy surveillance`.",
                ephemeral=True,
            )
            return

        report = await self.db.get_surveillance_report(gid, target.id)
        user_data = report["user"]
        history = report["history"]

        if not user_data:
            await interaction.followup.send("No data on file for this citizen.", ephemeral=True)
            return

        from config.ranks import get_rank, EXECUTION_THRESHOLD
        current_score = float(user_data["score"])
        rank = get_rank(current_score)

        total_events = len(history)
        positive_events = sum(1 for h in history if h["delta"] > 0)
        negative_events = sum(1 for h in history if h["delta"] < 0)
        net_delta = sum(h["delta"] for h in history)

        reason_counts: dict[str, int] = {}
        for h in history:
            r = h["reason"] or "unknown"
            reason_counts[r] = reason_counts.get(r, 0) + 1
        top_reasons = sorted(reason_counts.items(), key=lambda x: -x[1])[:5]

        delta_str = f"+{net_delta:.2f}" if net_delta >= 0 else f"{net_delta:.2f}"

        if current_score <= EXECUTION_THRESHOLD:
            risk = "CRITICAL · EXECUTION IMMINENT"
        elif current_score < 650:
            risk = "HIGH"
        elif current_score < 700:
            risk = "ELEVATED"
        elif current_score < 750:
            risk = "MODERATE"
        else:
            risk = "LOW"

        embed = discord.Embed(color=0x1a1a2e, title="中华人民共和国社会信用局 · 机密档案")
        embed.add_field(name="SUBJECT", value=str(target), inline=True)
        embed.add_field(name="CURRENT SCORE", value=f"{current_score:.2f}", inline=True)
        embed.add_field(name="RANK", value=rank["name"], inline=True)
        embed.add_field(name="YUAN BALANCE", value=f"¥{user_data['yuan']:,}", inline=True)
        embed.add_field(name="ALL-TIME HIGH", value=f"{float(user_data['highest_score']):.2f}", inline=True)
        embed.add_field(name="ALL-TIME LOW", value=f"{float(user_data['lowest_score']):.2f}", inline=True)
        embed.add_field(name="CHECKIN STREAK", value=str(user_data["checkin_streak"] or 0), inline=True)
        embed.add_field(name="PROPAGANDA WINS", value=str(user_data["propaganda_wins"] or 0), inline=True)
        embed.add_field(name="THREAT LEVEL", value=risk, inline=True)
        embed.add_field(
            name="30-DAY NET CHANGE",
            value=f"{delta_str} across {total_events} events · {positive_events} positive · {negative_events} negative",
            inline=False,
        )
        if top_reasons:
            embed.add_field(
                name="TOP ACTIVITY (30 DAYS)",
                value="\n".join(f"`{r}` × {c}" for r, c in top_reasons),
                inline=False,
            )
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)

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
