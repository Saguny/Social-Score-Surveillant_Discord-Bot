import random
import time
import discord
from discord import app_commands
from discord.ext import commands
from config.shop import SHOP_ITEMS, BADGE_DISPLAY, COSMETIC_META

_INVESTIGATION_BOUNTY_REWARD = 8000

_CATEGORY_TITLES = {
    "core":     "中华人民共和国社会信用局 · 核心项目",
    "economy":  "中华人民共和国社会信用局 · 经济 · 互动",
    "misc":     "中华人民共和国社会信用局 · 杂项",
    "lottery":  "中华人民共和国社会信用局 · 国家彩票",
    "cosmetic": "中华人民共和国社会信用局 · 装饰品 · 声望",
}

_CATEGORY_LABELS = {
    "core":     "Core",
    "economy":  "Economy",
    "misc":     "Misc",
    "lottery":  "Lottery",
    "cosmetic": "Cosmetic",
}

_THUMBNAIL = "attachment://market.png"

_COSMETIC_ORDER = ["verified", "figure", "influencer", "associate", "asset", "eternal_chairman"]
_LOTTERY_ORDER  = ["lottery", "lottery_standard", "lottery_premium", "lottery_elite", "lottery_chairman"]

_LOTTERY_TIERS = {
    "lottery":          {"win": (600,      1_000),   "jackpot": (2_000,     4_000)},
    "lottery_standard": {"win": (3_000,    5_000),   "jackpot": (10_000,   20_000)},
    "lottery_premium":  {"win": (12_000,  18_000),   "jackpot": (40_000,   80_000)},
    "lottery_elite":    {"win": (60_000,  90_000),   "jackpot": (200_000, 400_000)},
    "lottery_chairman": {"win": (300_000, 500_000),  "jackpot": (1_000_000, 2_000_000)},
}


def _build_shop_embeds(username: str = "yourname") -> dict[str, discord.Embed]:
    e_cosmetic = discord.Embed(color=0xFFB347, title=_CATEGORY_TITLES["cosmetic"])
    e_cosmetic.set_thumbnail(url=_THUMBNAIL)
    for item_id in _COSMETIC_ORDER:
        item = SHOP_ITEMS.get(item_id)
        if not item:
            continue
        meta = COSMETIC_META.get(item_id, {})
        label = meta.get("label", item["name"].upper())
        suffix = meta.get("suffix", "")
        scope = "Global" if item.get("global") else "Server-wide"
        preview = f"{username} {suffix}" if suffix else username
        e_cosmetic.add_field(
            name=f"/buy {item_id}  ·  ¥{item['cost']:,}  ·  {scope}",
            value=f"{preview}\n{item['description']}",
            inline=False,
        )

    def _fmt_yuan(n):
        if n >= 1_000_000: return f"¥{n//1_000_000}M"
        if n >= 1_000:     return f"¥{n//1_000}K"
        return f"¥{n}"

    e_lottery = discord.Embed(
        color=0xFFD700,
        title=_CATEGORY_TITLES["lottery"],
        description="70% lose · 20% win · 10% jackpot\nAdd a `target` to gift a ticket.",
    )
    e_lottery.set_thumbnail(url=_THUMBNAIL)
    for item_id in _LOTTERY_ORDER:
        item = SHOP_ITEMS.get(item_id)
        tier = _LOTTERY_TIERS.get(item_id)
        if not item or not tier:
            continue
        w0, w1 = tier["win"]
        j0, j1 = tier["jackpot"]
        e_lottery.add_field(
            name=f"{item['name']}  ·  ¥{item['cost']:,}",
            value=f"Win {_fmt_yuan(w0)}–{_fmt_yuan(w1)}\nJackpot {_fmt_yuan(j0)}–{_fmt_yuan(j1)}",
            inline=True,
        )
    dono_item = SHOP_ITEMS.get("lottery_dono")
    if dono_item:
        e_lottery.add_field(
            name=f"{dono_item['name']}  ·  Your entire balance",
            value="50% · Double your balance\n50% · Lose everything",
            inline=True,
        )

    by_cat: dict[str, list] = {}
    for item_id, item in SHOP_ITEMS.items():
        cat = item.get("category", "core")
        if cat not in ("cosmetic", "lottery"):
            by_cat.setdefault(cat, []).append((item_id, item))

    embeds: dict[str, discord.Embed] = {"cosmetic": e_cosmetic, "lottery": e_lottery}
    for cat in ("core", "economy", "misc"):
        embed = discord.Embed(color=0xCC0000, title=_CATEGORY_TITLES[cat])
        embed.set_thumbnail(url=_THUMBNAIL)
        for item_id, item in by_cat.get(cat, []):
            embed.add_field(
                name=f"/buy {item_id}  ·  ¥{item['cost']:,}",
                value=item['description'],
                inline=False,
            )
        embeds[cat] = embed

    return embeds


class ShopView(discord.ui.View):
    def __init__(self, embeds: dict[str, discord.Embed], active: str = "core"):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.active = active
        self._refresh_buttons()

    def _refresh_buttons(self):
        self.clear_items()
        for cat, label in _CATEGORY_LABELS.items():
            style = discord.ButtonStyle.primary if cat == self.active else discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label, style=style, custom_id=cat)
            btn.callback = self._make_callback(cat)
            self.add_item(btn)

    def _make_callback(self, cat: str):
        async def callback(interaction: discord.Interaction):
            self.active = cat
            self._refresh_buttons()
            await interaction.response.edit_message(embed=self.embeds[cat], view=self)
        return callback


class TransferView(discord.ui.View):
    def __init__(self, sender: discord.Member, recipient: discord.Member, amount: int, sender_balance: int):
        super().__init__(timeout=60)
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.sender_balance = sender_balance
        self.done = False

    async def _finish(self, interaction: discord.Interaction, confirmed: bool):
        if self.done:
            await interaction.response.defer()
            return
        self.done = True
        self.clear_items()

        if confirmed:
            db = interaction.client.db
            gid = interaction.guild.id
            if not await db.spend_yuan(gid, self.sender.id, self.amount):
                user = await db.get_user(gid, self.sender.id)
                embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 转账")
                embed.add_field(
                    name="TRANSFER FAILED",
                    value=f"Insufficient funds. Balance: ¥{user['yuan']:,} · Required: ¥{self.amount:,}",
                    inline=False,
                )
                await interaction.response.edit_message(embed=embed, view=self)
                return

            await db.adjust_yuan(gid, self.recipient.id, self.amount)
            recipient_data = await db.get_user(gid, self.recipient.id)
            sender_new = self.sender_balance - self.amount
            recipient_new = recipient_data["yuan"]

            ack = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局 · 转账")
            ack.add_field(name="TRANSFER SENT", value=f"¥{self.amount:,} dispatched to {self.recipient.mention}.", inline=False)
            await interaction.response.edit_message(embed=ack, view=self)

            public = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局 · 转账")
            public.add_field(name="YUAN TRANSFER", value=f"{self.sender.mention} -> {self.recipient.mention}", inline=False)
            public.add_field(name="AMOUNT", value=f"¥{self.amount:,}", inline=False)
            public.add_field(
                name=f"{self.sender.display_name}",
                value=f"¥{self.sender_balance:,} -> ¥{sender_new:,}",
                inline=True,
            )
            public.add_field(
                name=f"{self.recipient.display_name}",
                value=f"¥{recipient_new - self.amount:,} -> ¥{recipient_new:,}",
                inline=True,
            )
            public.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=public)
            return
        else:
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · 转账")
            embed.add_field(name="TRANSFER CANCELLED", value="The transaction has been voided.", inline=False)
            await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            await interaction.response.send_message("This is not your transfer.", ephemeral=True)
            return
        await self._finish(interaction, confirmed=True)

    @discord.ui.button(label="Nevermind", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.sender.id:
            await interaction.response.send_message("This is not your transfer.", ephemeral=True)
            return
        await self._finish(interaction, confirmed=False)

    async def on_timeout(self):
        self.done = True
        self.clear_items()


class RequestView(discord.ui.View):
    def __init__(self, requester: discord.Member, target: discord.Member, amount: int):
        super().__init__(timeout=300)
        self.requester = requester
        self.target = target
        self.amount = amount
        self.done = False

    async def _finish(self, interaction: discord.Interaction, accepted: bool):
        if self.done:
            await interaction.response.defer()
            return
        self.done = True
        self.clear_items()

        if accepted:
            db = interaction.client.db
            gid = interaction.guild.id
            if not await db.spend_yuan(gid, self.target.id, self.amount):
                user = await db.get_user(gid, self.target.id)
                embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 资金申请")
                embed.add_field(
                    name="REQUEST FAILED",
                    value=f"Insufficient funds. {self.target.mention} has ¥{user['yuan']:,} · Required: ¥{self.amount:,}",
                    inline=False,
                )
                await interaction.response.edit_message(embed=embed, view=self)
                return

            await db.adjust_yuan(gid, self.requester.id, self.amount)
            target_data = await db.get_user(gid, self.target.id)
            requester_data = await db.get_user(gid, self.requester.id)
            target_new = target_data["yuan"]
            requester_new = requester_data["yuan"]

            embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局 · 资金申请")
            embed.add_field(name="REQUEST FULFILLED", value=f"{self.target.mention} paid {self.requester.mention}", inline=False)
            embed.add_field(name="AMOUNT", value=f"¥{self.amount:,}", inline=False)
            embed.add_field(
                name=self.target.display_name,
                value=f"¥{target_new + self.amount:,} -> ¥{target_new:,}",
                inline=True,
            )
            embed.add_field(
                name=self.requester.display_name,
                value=f"¥{requester_new - self.amount:,} -> ¥{requester_new:,}",
                inline=True,
            )
            embed.timestamp = discord.utils.utcnow()
        else:
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 资金申请")
            embed.add_field(
                name="REQUEST DECLINED",
                value=f"{self.target.mention} refused {self.requester.mention}'s request of ¥{self.amount:,}.",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()

        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("This request is not addressed to you.", ephemeral=True)
            return
        await self._finish(interaction, accepted=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.target.id:
            await interaction.response.send_message("This request is not addressed to you.", ephemeral=True)
            return
        await self._finish(interaction, accepted=False)

    async def on_timeout(self):
        self.done = True
        self.clear_items()


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    def _post_score(self, interaction: discord.Interaction, member: discord.Member, old: float, new: float):
        self.bot.dispatch("score_change", interaction.guild, member, interaction.channel, old, new)

    @app_commands.command(name="shop", description="Browse the Social Credit Bureau's shop")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        embeds = _build_shop_embeds(username=str(interaction.user))
        view = ShopView(embeds, active="core")
        await interaction.followup.send(
            embed=embeds["core"],
            view=view,
            file=discord.File("images/market.png", filename="market.png"),
        )

    @app_commands.command(name="yuan", description="Check your Yuan balance")
    async def yuan(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        user = await self.db.get_user(interaction.guild.id, interaction.user.id)
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
        embed.add_field(name="CITIZEN", value=await self.bot.format_user_full(interaction.user, interaction.guild.id), inline=False)
        embed.add_field(name="BALANCE", value=f"¥{user['yuan']:,}", inline=True)
        embed.add_field(name="TOTAL EARNED", value=f"¥{user['total_yuan_earned']:,}", inline=True)
        embed.add_field(name="TOTAL SPENT", value=f"¥{user['total_yuan_spent']:,}", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="buy", description="Purchase an item from the shop")
    @app_commands.describe(
        item="Item ID (see /shop)",
        target="Target citizen (required for some items)",
        text="Text argument (required for some items)",
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

        _public_items = {"lottery", "lottery_standard", "lottery_premium", "lottery_elite", "lottery_chairman", "lottery_dono", "dispute", "inspection", "criticism", "pact"}
        await interaction.response.defer(ephemeral=item not in _public_items)

        if item == "protection" and target and await self.db.get_effect(interaction.guild.id, target.id, "protection"):
            await interaction.followup.send(
                f"{target.mention} already has active Political Protection.", ephemeral=True
            )
            return

        if cfg.get("cosmetic"):
            if cfg.get("global"):
                if uid in self.bot.ec_users:
                    await interaction.followup.send("You have already purchased this global cosmetic.", ephemeral=True)
                    return
            else:
                owned = await self.db.get_cosmetic_badges(gid, uid)
                if item in owned:
                    await interaction.followup.send("You already have this cosmetic on this server.", ephemeral=True)
                    return

        cost = cfg["cost"]
        if item == "rehabilitate":
            rehab_count = await self.db.get_rehabilitation_count(gid, uid)
            cost = cfg["cost"] * (2 ** rehab_count)

        if item == "denounce" and target:
            last_denounce = await self.db.get_last_action_time(gid, uid, "denounce", target.id)
            if last_denounce and int(time.time()) - last_denounce < 172800:
                remaining = 172800 - (int(time.time()) - last_denounce)
                hours = remaining // 3600
                await interaction.followup.send(
                    f"Denouncement cooldown active. You may target this citizen again in {hours}h.",
                    ephemeral=True,
                )
                return

        if not await self.db.spend_yuan(gid, uid, cost):
            balance = (await self.db.get_user(gid, uid))["yuan"]
            await interaction.followup.send(
                f"Insufficient funds. Balance: ¥{balance:,} · Cost: ¥{cost:,}", ephemeral=True
            )
            return

        await self.db.log_transaction(gid, uid, item, cost, target.id if target else None)
        await self.db.increment_items_bought(gid, uid)
        await self._dispatch(interaction, item, cfg, target, text, cost)

    async def _apply_defense_chain(self, gid: int, target_id: int, base_delta: float) -> tuple[float, str | None]:
        if await self.db.get_effect(gid, target_id, "criticism"):
            base_delta *= 2
        if await self.db.consume_effect(gid, target_id, "exception"):
            return 0.0, "exception"
        if await self.db.consume_effect(gid, target_id, "immunity"):
            if random.random() < 0.5:
                return 0.0, "immunity"
        reduction = 1.0
        if await self.db.consume_effect(gid, target_id, "appeal"):
            reduction *= 0.5
        if await self.db.consume_effect(gid, target_id, "protection"):
            reduction *= 0.5
        if await self.db.get_effect(gid, target_id, "legal_rep"):
            reduction *= 0.5
        return round(base_delta * reduction, 2), None

    async def _dispatch(self, interaction, item_id, cfg, target, text, cost):
        gid = interaction.guild.id
        uid = interaction.user.id

        if item_id == "report":
            is_anon = await self.db.consume_effect(gid, uid, "anon_identity")
            delta, block = await self._apply_defense_chain(gid, target.id, -2.0)
            if block:
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
                msg = (
                    f"{target.mention} had an Administrative Exception on file. Report nullified."
                    if block == "exception" else
                    f"{target.mention}'s Citizen Immunity deflected the report."
                )
                embed.add_field(name="REPORT NULLIFIED", value=msg, inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            old, new = await self.db.update_score(gid, target.id, delta, "citizen report")
            await self.db.increment_reported(gid, target.id)
            await self.db.increment_filed_reports(gid, uid)
            report_num = await self.db.increment_report_counter(gid)
            reporter_name = "Unknown Citizen" if is_anon else await self.bot.format_user_full(interaction.user, gid)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(name="OFFICIAL REPORT FILED", value=target.mention, inline=False)
            embed.add_field(name="FILED BY", value=reporter_name, inline=True)
            embed.add_field(name="SCORE IMPACT", value=f"{delta:.2f}", inline=True)
            embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)
            self._post_score(interaction, target, old, new)

        elif item_id == "denounce":
            is_anon = await self.db.consume_effect(gid, uid, "anon_identity")
            delta, block = await self._apply_defense_chain(gid, target.id, -20.0)
            if block:
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
                msg = (
                    f"{target.mention} had an Administrative Exception on file. Denouncement nullified."
                    if block == "exception" else
                    f"{target.mention}'s Citizen Immunity deflected the denouncement."
                )
                embed.add_field(name="DENOUNCEMENT NULLIFIED", value=msg, inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
                return

            old, new = await self.db.update_score(gid, target.id, delta, "public denouncement")
            await self.db.increment_reported(gid, target.id)
            report_num = await self.db.increment_report_counter(gid)
            bounty = await self.db.consume_investigation_bounty(gid, target.id)
            if bounty:
                await self.db.adjust_yuan(gid, uid, bounty.get("reward", _INVESTIGATION_BOUNTY_REWARD))
            denouncer_name = "Unknown Citizen" if is_anon else await self.bot.format_user_full(interaction.user, gid)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公开谴责")
            embed.add_field(name="SUBJECT", value=target.mention, inline=False)
            embed.add_field(name="DENOUNCED BY", value=denouncer_name, inline=True)
            embed.add_field(name="STATED CRIME", value=text[:100], inline=False)
            embed.add_field(name="SCORE IMPACT", value=f"{delta:.2f}", inline=True)
            if bounty:
                embed.add_field(name="INVESTIGATION BOUNTY CLAIMED", value=f"+¥{bounty.get('reward', _INVESTIGATION_BOUNTY_REWARD):,}", inline=False)
            embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Your denouncement has been filed.", ephemeral=True)
            self._post_score(interaction, target, old, new)

        elif item_id == "surveillance":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "surveillance", expires_at, {"target_id": target.id})
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="INTELLIGENCE PACKAGE ACQUIRED",
                value=f"Dossier on {target.mention} is ready.\nUse `/surveillance_report` within 30 days to redeem.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "rehabilitate":
            recipient = target if target else interaction.user
            old, new = await self.db.update_score(gid, recipient.id, 3.0, "rehabilitation certificate")
            if target:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="REHABILITATION GIFT", value=f"{interaction.user.mention} gifted a Rehabilitation Program to {target.mention}", inline=False)
                embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="REHABILITATION APPROVED", value=f"Score adjusted: {old:.2f} -> {new:.2f}", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
            self._post_score(interaction, recipient, old, new)

        elif item_id == "appeal":
            recipient = target if target else interaction.user
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, recipient.id, "appeal", expires_at)
            if target:
                embed = discord.Embed(color=0x1a3a5c, title="中华人民共和国社会信用局")
                embed.add_field(name="APPEAL GIFT", value=f"{interaction.user.mention} filed an Appeal on behalf of {target.mention}", inline=False)
                embed.add_field(name="EFFECT", value="Their next incoming penalty within 12 hours will be reduced by 50%. Single use.", inline=False)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0x1a3a5c, title="中华人民共和国社会信用局")
                embed.add_field(name="APPEAL FILED", value="The next negative score action against you within 12 hours will be reduced by 50%. Single use.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "exception":
            recipient = target if target else interaction.user
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, recipient.id, "exception", expires_at)
            if target:
                embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
                embed.add_field(name="EXCEPTION GIFT", value=f"{interaction.user.mention} granted an Administrative Exception to {target.mention}", inline=False)
                embed.add_field(name="EFFECT", value="Their next negative score action within 24 hours will be completely nullified. Single use.", inline=False)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
                embed.add_field(name="EXCEPTION GRANTED", value="The next negative score action against you within 24 hours will be completely nullified.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "reeducation":
            if await self.db.get_effect(gid, target.id, "freeze"):
                await interaction.followup.send(
                    f"{target.mention} is already score-frozen.", ephemeral=True
                )
                return
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, target.id, "freeze", expires_at)
            self.db.invalidate_effect_cache(gid, target.id, "freeze")
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 再教育营")
            embed.add_field(
                name="RE-EDUCATION SENTENCE ISSUED",
                value=f"{target.mention}'s social credit score is frozen for 2 hours by order of the bureau.",
                inline=False,
            )
            await interaction.followup.send(embed=embed)

        elif item_id in _LOTTERY_TIERS:
            tier = _LOTTERY_TIERS[item_id]
            recipient = target if target else interaction.user
            gifted = target is not None
            recipient_name = await self.bot.format_user_full(recipient, gid)
            buyer_name = await self.bot.format_user_full(interaction.user, gid)
            roll = random.random()
            if roll < 0.7:
                net = 0 if gifted else -cost
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · 国家彩票")
                if gifted:
                    embed.add_field(name="TICKET PURCHASED BY", value=buyer_name, inline=True)
                    embed.add_field(name="FOR", value=recipient_name, inline=True)
                else:
                    embed.add_field(name="CITIZEN", value=buyer_name, inline=False)
                embed.add_field(name="RESULT", value="Better luck next time. The Party keeps your entry.", inline=False)
                embed.add_field(name="YUAN CHANGE", value=f"-¥{cost:,}", inline=False)
                await self.db.update_lottery_stats(gid, recipient.id, False, net)
            elif roll < 0.9:
                winnings = random.randint(*tier["win"])
                net = winnings if gifted else winnings - cost
                await self.db.adjust_yuan(gid, recipient.id, winnings)
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 国家彩票")
                if gifted:
                    embed.add_field(name="TICKET PURCHASED BY", value=buyer_name, inline=True)
                    embed.add_field(name="FOR", value=recipient_name, inline=True)
                else:
                    embed.add_field(name="CITIZEN", value=buyer_name, inline=False)
                embed.add_field(name="WINNER", value="The Party smiles upon you.", inline=False)
                embed.add_field(name="YUAN CHANGE", value=f"+¥{winnings:,} · net {net:+,}", inline=False)
                await self.db.update_lottery_stats(gid, recipient.id, True, net)
            else:
                winnings = random.randint(*tier["jackpot"])
                net = winnings if gifted else winnings - cost
                await self.db.adjust_yuan(gid, recipient.id, winnings)
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 国家彩票")
                if gifted:
                    embed.add_field(name="TICKET PURCHASED BY", value=buyer_name, inline=True)
                    embed.add_field(name="FOR", value=recipient_name, inline=True)
                else:
                    embed.add_field(name="CITIZEN", value=buyer_name, inline=False)
                embed.add_field(name="JACKPOT", value="Extraordinary fortune. The state bestows its blessing.", inline=False)
                embed.add_field(name="YUAN CHANGE", value=f"+¥{winnings:,} · net {net:+,}", inline=False)
                await self.db.update_lottery_stats(gid, recipient.id, True, net)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "lottery_dono":
            user_row = await self.db.get_user(gid, uid)
            balance  = int(user_row["yuan"]) if user_row else 0
            name     = await self.bot.format_user_full(interaction.user, gid)
            if balance <= 0:
                await interaction.followup.send("You have no yuan to wager.", ephemeral=True)
                return
            won = random.random() < 0.5
            if won:
                await self.db.adjust_yuan(gid, uid, balance)
                await self.db.update_lottery_stats(gid, uid, True, balance)
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 双倍或无")
                embed.add_field(name="CITIZEN", value=name, inline=False)
                embed.add_field(name="RESULT", value="The Party smiles upon your boldness.", inline=False)
                embed.add_field(name="WAGERED", value=f"¥{balance:,}", inline=True)
                embed.add_field(name="NEW BALANCE", value=f"¥{balance * 2:,}", inline=True)
            else:
                await self.db.set_yuan(gid, uid, 0)
                await self.db.update_lottery_stats(gid, uid, False, -balance)
                embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · 双倍或无")
                embed.add_field(name="CITIZEN", value=name, inline=False)
                embed.add_field(name="RESULT", value="The Party has confiscated your assets.", inline=False)
                embed.add_field(name="LOST", value=f"¥{balance:,}", inline=True)
                embed.add_field(name="NEW BALANCE", value="¥0", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "tip":
            embed = discord.Embed(color=0x555555, title="中华人民共和国社会信用局 · 匿名举报")
            embed.add_field(name="SUBJECT", value=target.mention, inline=False)
            embed.add_field(name="SUBMITTED BY", value="Unknown Citizen", inline=True)
            embed.add_field(name="TIP", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Your tip has been submitted anonymously.", ephemeral=True)

        elif item_id == "model_citizen":
            recipient = target if target else interaction.user
            old, new = await self.db.update_score(gid, recipient.id, 1.0, "model citizen commendation")
            if target:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="MODEL CITIZEN COMMENDATION", value=f"{interaction.user.mention} has nominated {target.mention} as a Model Citizen", inline=False)
                embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your commendation has been filed.", ephemeral=True)
            else:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="MODEL CITIZEN AWARD", value=f"The Party commends your loyalty. Score: {old:.2f} -> {new:.2f}", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)
            self._post_score(interaction, recipient, old, new)

        elif item_id == "dispute":
            buyer_wins = random.random() < 0.5
            winner = interaction.user if buyer_wins else target
            loser = target if buyer_wins else interaction.user
            w_old, w_new = await self.db.update_score(gid, winner.id, 2.0, "dispute resolution victory")
            l_old, l_new = await self.db.update_score(gid, loser.id, -2.0, "dispute resolution loss")
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 争议裁决")
            challenger_name = await self.bot.format_user_full(interaction.user, gid)
            defendant_name = await self.bot.format_user_full(target, gid)
            winner_name = await self.bot.format_user_full(winner, gid)
            loser_name = await self.bot.format_user_full(loser, gid)
            embed.add_field(name="CHALLENGER", value=challenger_name, inline=True)
            embed.add_field(name="DEFENDANT", value=defendant_name, inline=True)
            embed.add_field(name="OUTCOME", value=f"{winner_name} wins +2.00 · {loser_name} loses -2.00", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)
            self._post_score(interaction, winner, w_old, w_new)
            self._post_score(interaction, loser, l_old, l_new)

        elif item_id == "investigation":
            extra_bounty = 0
            if text:
                try:
                    extra_bounty = max(0, int(text.replace(",", "").strip()))
                except ValueError:
                    pass
            if extra_bounty > 0 and not await self.db.spend_yuan(gid, uid, extra_bounty):
                balance = (await self.db.get_user(gid, uid))["yuan"]
                await interaction.followup.send(
                    f"Insufficient funds for ¥{extra_bounty:,} extra bounty (balance: ¥{balance:,}). Base bounty applied.",
                    ephemeral=True,
                )
                extra_bounty = 0
            total_bounty = _INVESTIGATION_BOUNTY_REWARD + extra_bounty
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, target.id, "investigation", expires_at, {"buyer_id": uid, "reward": total_bounty})
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局")
            bounty_line = f"¥{total_bounty:,} bounty" + (f" (¥{_INVESTIGATION_BOUNTY_REWARD:,} base + ¥{extra_bounty:,} added)" if extra_bounty else "")
            embed.add_field(
                name="SPECIAL INVESTIGATION OPENED",
                value=f"{bounty_line} placed on {target.mention}.\nThe next citizen to file a report on them will receive the reward.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "protection":
            expires_at = int(time.time()) + 315360000
            await self.db.add_effect(gid, target.id, "protection", expires_at)
            embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
            embed.add_field(
                name="POLITICAL PROTECTION GRANTED",
                value=f"{target.mention} is under political protection.\nThe first negative action against them will be reduced by 50%. Lasts until triggered.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "inquiry":
            attacker_id = await self.db.get_last_attacker(gid, uid)
            embed = discord.Embed(color=0x1a1a2e, title="中华人民共和国社会信用局 · 内部调查")
            if attacker_id:
                attacker = interaction.guild.get_member(attacker_id)
                attacker_name = await self.bot.format_user_full(attacker, gid) if attacker else f"User {attacker_id}"
                embed.add_field(name="LAST KNOWN AGGRESSOR", value=attacker_name, inline=False)
            else:
                embed.add_field(name="RESULT", value="No reports or denouncements on file against you.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "criticism":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, target.id, "criticism", expires_at)
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局")
            embed.add_field(
                name="COORDINATED CRITICISM ACTIVE",
                value=f"All negative score actions against {target.mention} deal double score loss for 24 hours.",
                inline=False,
            )
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)

        elif item_id == "inspection":
            victim_id = await self.db.get_random_active_user(gid, uid)
            if not victim_id:
                await interaction.followup.send("No eligible citizens found in this server.", ephemeral=True)
                return
            old, new = await self.db.update_score(gid, victim_id, -1.0, "compliance inspection")
            victim = interaction.guild.get_member(victim_id)
            victim_name = await self.bot.format_user_full(victim, gid) if victim else f"Citizen {victim_id}"
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 合规检查")
            embed.add_field(name="SELECTED CITIZEN", value=victim_name, inline=False)
            embed.add_field(name="RESULT", value=f"Score: {old:.2f} -> {new:.2f}", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)
            if victim:
                self._post_score(interaction, victim, old, new)

        elif item_id == "history_review":
            history = await self.db.get_score_history_brief(gid, target.id, limit=20)
            embed = discord.Embed(color=0x1a1a2e, title="中华人民共和国社会信用局 · 历史审查")
            embed.add_field(name="SUBJECT", value=await self.bot.format_user_full(target, gid), inline=False)
            if history:
                lines = []
                for h in history:
                    sign = "+" if h["delta"] >= 0 else ""
                    from datetime import datetime, timezone
                    ts = datetime.fromtimestamp(h["timestamp"], tz=timezone.utc).strftime("%m/%d %H:%M")
                    lines.append(f"`{ts}` {sign}{h['delta']:.2f} · {h['reason'] or 'unknown'}")
                embed.add_field(name="LAST 20 EVENTS", value="\n".join(lines[:20])[:1024], inline=False)
            else:
                embed.add_field(name="RESULT", value="No score history on file.", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "legal_rep":
            recipient = target if target else interaction.user
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, recipient.id, "legal_rep", expires_at)
            if target:
                embed = discord.Embed(color=0x1a3a5c, title="中华人民共和国社会信用局")
                embed.add_field(name="LEGAL REPRESENTATION GIFT", value=f"{interaction.user.mention} retained legal counsel for {target.mention}", inline=False)
                embed.add_field(name="EFFECT", value="All negative score actions against them are reduced by 50% for 12 hours.", inline=False)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0x1a3a5c, title="中华人民共和国社会信用局")
                embed.add_field(name="LEGAL REPRESENTATION ACTIVE", value="All negative score actions against you are reduced by 50% for 12 hours.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "anon_identity":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "anon_identity", expires_at)
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="ALTERNATE IDENTITY ACTIVE",
                value="Your next report or denouncement will appear as Unknown Citizen. Single use.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "immunity":
            recipient = target if target else interaction.user
            expires_at = int(time.time()) + (86400 * 7)
            await self.db.add_effect(gid, recipient.id, "immunity", expires_at)
            if target:
                embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
                embed.add_field(name="IMMUNITY GIFT", value=f"{interaction.user.mention} secured Citizen Immunity for {target.mention}", inline=False)
                embed.add_field(name="EFFECT", value="50% chance to completely block the next negative action against them. Single use.", inline=False)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
                embed.add_field(name="CITIZEN IMMUNITY ACTIVE", value="50% chance to completely block the next negative action against you. Single use.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "pact":
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, uid, "appeal", expires_at)
            await self.db.add_effect(gid, target.id, "appeal", expires_at)
            embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局")
            embed.add_field(
                name="MUTUAL ASSISTANCE PACT SEALED",
                value=f"You and {target.mention} both now carry a 50% reduction shield on your next incoming penalty.",
                inline=False,
            )
            await interaction.followup.send(embed=embed)

        elif item_id == "media_coverage":
            recipient = target if target else interaction.user
            expires_at = int(time.time()) + cfg["duration"]
            await self.db.add_effect(gid, recipient.id, "media_coverage", expires_at)
            if target:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="MEDIA COVERAGE GIFT", value=f"{interaction.user.mention} arranged State Media Coverage for {target.mention}", inline=False)
                embed.add_field(name="EFFECT", value="Their next organic positive score gain will be doubled and broadcast publicly.", inline=False)
                if text:
                    embed.add_field(name="MESSAGE", value=text[:200], inline=False)
                embed.timestamp = discord.utils.utcnow()
                await interaction.channel.send(embed=embed)
                await interaction.followup.send("Your gift has been delivered.", ephemeral=True)
            else:
                embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局")
                embed.add_field(name="STATE MEDIA COVERAGE ACTIVE", value="Your next organic positive score gain will be doubled and broadcast publicly.", inline=False)
                await interaction.followup.send(embed=embed, ephemeral=True)

        elif item_id == "fabricated_evidence":
            await self.db.add_fabricated_history(gid, target.id, text)
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局")
            embed.add_field(
                name="EVIDENCE PLANTED",
                value=f"An unverified entry has been inserted into {target.mention}'s score history.",
                inline=False,
            )
            await interaction.followup.send(embed=embed, ephemeral=True)

        elif cfg.get("cosmetic"):
            meta = COSMETIC_META.get(item_id, {})
            color = meta.get("color", 0xFFD700)
            label = meta.get("label", item_id.upper())
            note = meta.get("note", "Your cosmetic status has been recorded in the bureau's registry.")
            if item_id == "eternal_chairman":
                await self.db.add_eternal_chairman(uid)
                self.bot.ec_users.add(uid)
            else:
                await self.db.add_cosmetic_badge(gid, uid, item_id)
            embed = discord.Embed(color=color, title="中华人民共和国社会信用局")
            embed.add_field(name=f"STATUS GRANTED: {label}", value=note, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="transfer", description="Transfer Yuan to another citizen")
    @app_commands.describe(recipient="The citizen to send Yuan to", amount="Amount of Yuan to transfer")
    async def transfer(self, interaction: discord.Interaction, recipient: discord.Member, amount: int):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = interaction.user.id

        if recipient.bot or recipient.id == uid:
            await interaction.followup.send("Invalid recipient.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("Amount must be greater than zero.", ephemeral=True)
            return

        user = await self.db.get_user(gid, uid)
        if user["yuan"] < amount:
            await interaction.followup.send(
                f"Insufficient funds. Balance: ¥{user['yuan']:,} · Requested: ¥{amount:,}", ephemeral=True
            )
            return

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 转账")
        embed.add_field(name="TRANSFER REQUEST", value=f"Send ¥{amount:,} to {recipient.mention}?", inline=False)
        embed.add_field(name="FROM", value=interaction.user.mention, inline=True)
        embed.add_field(name="TO", value=recipient.mention, inline=True)
        embed.add_field(name="AMOUNT", value=f"¥{amount:,}", inline=True)
        embed.add_field(name="YOUR BALANCE AFTER", value=f"¥{user['yuan'] - amount:,}", inline=False)
        embed.timestamp = discord.utils.utcnow()

        view = TransferView(interaction.user, recipient, amount, user["yuan"])
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="requestyuan", description="Request Yuan from another citizen")
    @app_commands.describe(citizen="The citizen to request Yuan from", amount="Amount of Yuan to request", reason="Optional reason for the request")
    async def requestyuan(self, interaction: discord.Interaction, citizen: discord.Member, amount: int, reason: str = None):
        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id

        if citizen.bot or citizen.id == uid:
            await interaction.followup.send("Invalid target.", ephemeral=True)
            return
        if amount <= 0:
            await interaction.followup.send("Amount must be greater than zero.", ephemeral=True)
            return

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 资金申请")
        embed.add_field(name="YUAN REQUEST", value=f"{interaction.user.mention} is requesting ¥{amount:,} from {citizen.mention}", inline=False)
        embed.add_field(name="FROM", value=citizen.mention, inline=True)
        embed.add_field(name="TO", value=interaction.user.mention, inline=True)
        embed.add_field(name="AMOUNT", value=f"¥{amount:,}", inline=True)
        if reason:
            embed.add_field(name="REASON", value=reason[:200], inline=False)
        embed.timestamp = discord.utils.utcnow()

        view = RequestView(interaction.user, citizen, amount)
        await interaction.followup.send(embed=embed, view=view)

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
        embed.add_field(name="SUBJECT", value=await self.bot.format_user_full(target, gid), inline=True)
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
                value="\n".join(f"`{r}` x{c}" for r, c in top_reasons),
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
                f"Insufficient funds. Confession costs ¥{cost:,} at your current score. Balance: ¥{user['yuan']:,}",
                ephemeral=True,
            )
            return

        await self.db.log_transaction(gid, uid, "confess", cost)
        old, new = await self.db.update_score(gid, uid, 0.5, "public confession")

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 公开认罪")
        embed.add_field(name="CITIZEN", value=await self.bot.format_user_full(interaction.user, gid), inline=False)
        embed.add_field(name="CONFESSION", value=text[:200], inline=False)
        embed.add_field(name="COST", value=f"¥{cost:,}", inline=True)
        embed.add_field(name="SCORE ADJUSTMENT", value=f"{old:.2f} -> {new:.2f}", inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)
        self._post_score(interaction, interaction.user, old, new)

    @buy.autocomplete("item")
    async def item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        return [
            app_commands.Choice(name=f"{v['name']} · ¥{v['cost']:,}", value=k)
            for k, v in SHOP_ITEMS.items()
            if current.lower() in k or current.lower() in v["name"].lower()
        ][:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
