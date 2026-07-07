import random
import time
import discord
import asyncio
from discord import app_commands
from discord.ext import commands
from config.shop import SHOP_ITEMS, BADGE_DISPLAY, COSMETIC_META, GACHA_UPGRADE_TIERS
from cogs.achievements import unlock as unlock_achievement, check_milestone

_INVESTIGATION_BOUNTY_REWARD = 8000

_CATEGORY_DESCRIPTIONS = {
    "core":     "Standard procurement items. Penalties, protections, and certifications.",
    "economy":  "Economic instruments. Transfers, contests, and financial actions.",
    "misc":     "Auxiliary services. Intelligence, evidence, and administrative tools.",
    "lottery":  "State Lottery Commission. Participation is voluntary. Outcomes are not.",
    "cosmetic": "Prestige registry. Status distinctions recorded in the Bureau's permanent files.",
    "gacha":    "Waifu Bureau upgrades. Permanent enhancements to your gacha account. Cost increases each tier.",
}

_CATEGORY_LABELS = {
    "core":     "STANDARD",
    "economy":  "ECONOMIC",
    "misc":     "SERVICES",
    "lottery":  "LOTTERY",
    "cosmetic": "PRESTIGE",
    "gacha":    "WAIFU BUREAU",
}

_THUMBNAIL         = "attachment://market.png"
_TREASURY_THUMBNAIL = "attachment://treasury.png"

_COSMETIC_ORDER = ["verified", "figure", "influencer", "associate", "asset", "eternal_chairman"]
_LOTTERY_ORDER  = ["lottery", "lottery_standard", "lottery_premium", "lottery_elite", "lottery_chairman"]

_LOTTERY_TIERS = {
    "lottery":          {"win": (600,      1_000),   "jackpot": (2_000,     4_000)},
    "lottery_standard": {"win": (3_000,    5_000),   "jackpot": (10_000,   20_000)},
    "lottery_premium":  {"win": (12_000,  18_000),   "jackpot": (40_000,   80_000)},
    "lottery_elite":    {"win": (60_000,  90_000),   "jackpot": (200_000, 400_000)},
    "lottery_chairman": {"win": (300_000, 500_000),  "jackpot": (1_000_000, 2_000_000)},
}

_PUBLIC_ITEMS = {
    "lottery", "lottery_standard", "lottery_premium", "lottery_elite",
    "lottery_chairman", "lottery_dono", "dispute", "inspection", "criticism", "pact",
}


def _build_items_for_cat() -> dict[str, list[tuple[str, dict]]]:
    cat_items: dict[str, list] = {}
    for item_id in _COSMETIC_ORDER:
        if item_id in SHOP_ITEMS:
            cat_items.setdefault("cosmetic", []).append((item_id, SHOP_ITEMS[item_id]))
    for item_id in _LOTTERY_ORDER + ["lottery_dono"]:
        if item_id in SHOP_ITEMS:
            cat_items.setdefault("lottery", []).append((item_id, SHOP_ITEMS[item_id]))
    for item_id, item in SHOP_ITEMS.items():
        cat = item.get("category", "core")
        if cat not in ("cosmetic", "lottery"):
            cat_items.setdefault(cat, []).append((item_id, item))
    return cat_items


async def _build_shop_embeds(username: str = "yourname", db=None, user_id: int | None = None, guild_id: int | None = None, _gacha_tiers: dict | None = None) -> dict[str, discord.Embed]:
    e_cosmetic = discord.Embed(color=0xFFB347, title="STATE PROCUREMENT OFFICE", description=_CATEGORY_DESCRIPTIONS["cosmetic"])
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
        title="STATE PROCUREMENT OFFICE",
        description=_CATEGORY_DESCRIPTIONS["lottery"] + "\n70% lose · 20% win · 10% jackpot · Add a `target` to gift a ticket.",
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

    gacha_tiers: dict[str, int] = _gacha_tiers or {}
    if not gacha_tiers and db and user_id and guild_id:
        tier_vals = await asyncio.gather(*(
            db.get_counter(user_id, f"gacha:upgrade:{guild_id}:{GACHA_UPGRADE_TIERS[iid]['key']}")
            for iid in GACHA_UPGRADE_TIERS
        ))
        gacha_tiers = {iid: int(v or 0) for iid, v in zip(GACHA_UPGRADE_TIERS, tier_vals)}

    embeds: dict[str, discord.Embed] = {"cosmetic": e_cosmetic, "lottery": e_lottery}
    for cat in ("core", "economy", "misc", "gacha"):
        embed = discord.Embed(color=0xCC0000, title="STATE PROCUREMENT OFFICE", description=_CATEGORY_DESCRIPTIONS[cat])
        embed.set_thumbnail(url=_THUMBNAIL)
        for item_id, item in by_cat.get(cat, []):
            if item_id in GACHA_UPGRADE_TIERS:
                tiers    = GACHA_UPGRADE_TIERS[item_id]
                cur_tier = gacha_tiers.get(item_id, 0)
                max_tier = len(tiers["costs"])
                if cur_tier >= max_tier:
                    name = f"/buy {item_id}  ·  MAXED"
                else:
                    name = f"/buy {item_id}  ·  ¥{tiers['costs'][cur_tier]:,}"
            else:
                name = f"/buy {item_id}  ·  ¥{item['cost']:,}"
            embed.add_field(name=name, value=item['description'], inline=False)
        embeds[cat] = embed

    return embeds


class ShopSelect(discord.ui.Select):
    def __init__(self, items: list[tuple[str, dict]], gacha_tiers: dict[str, int], cog):
        self.cog = cog
        options = []
        for item_id, item in items[:25]:
            if item_id == "lottery_dono":
                cost_str = "your entire balance"
            elif item_id in GACHA_UPGRADE_TIERS:
                meta = GACHA_UPGRADE_TIERS[item_id]
                tier = gacha_tiers.get(item_id, 0)
                cost_str = "MAXED" if tier >= len(meta["costs"]) else f"¥{meta['costs'][tier]:,}"
            else:
                cost_str = f"¥{item['cost']:,}"
            label = f"{item['name']} · {cost_str}"[:100]
            desc = ("Requires a target citizen." if item.get("requires_target") else item.get("description", ""))[:100]
            options.append(discord.SelectOption(label=label, value=item_id, description=desc))
        super().__init__(placeholder="Buy from this category...", options=options, min_values=1, max_values=1)

    async def callback(self, interaction: discord.Interaction):
        item_id = self.values[0]
        cfg = SHOP_ITEMS[item_id]
        if cfg.get("requires_target"):
            suffix = " and a reason" if cfg.get("requires_text") else ""
            await interaction.response.send_message(
                f"This item requires a target citizen{suffix}. Use `/buy {item_id} @citizen`.",
                ephemeral=True,
            )
            return
        await interaction.response.defer(ephemeral=item_id not in _PUBLIC_ITEMS)
        await self.cog._execute_buy(interaction, item_id)


class ShopView(discord.ui.View):
    def __init__(self, embeds: dict[str, discord.Embed], items_for_cat: dict, gacha_tiers: dict, cog, active: str = "core"):
        super().__init__(timeout=300)
        self.embeds = embeds
        self.items_for_cat = items_for_cat
        self.gacha_tiers = gacha_tiers
        self.cog = cog
        self.active = active
        self._refresh_ui()

    def _refresh_ui(self):
        self.clear_items()
        for cat, label in _CATEGORY_LABELS.items():
            style = discord.ButtonStyle.primary if cat == self.active else discord.ButtonStyle.secondary
            btn = discord.ui.Button(label=label, style=style, custom_id=cat)
            btn.callback = self._make_callback(cat)
            self.add_item(btn)
        items = self.items_for_cat.get(self.active, [])
        if items:
            self.add_item(ShopSelect(items, self.gacha_tiers, self.cog))

    def _make_callback(self, cat: str):
        async def callback(interaction: discord.Interaction):
            self.active = cat
            self._refresh_ui()
            await interaction.response.edit_message(embed=self.embeds[cat], view=self)
        return callback


class TransferView(discord.ui.View):
    def __init__(self, sender: discord.Member, recipient: discord.Member, amount: int, sender_balance: int, original_interaction: discord.Interaction):
        super().__init__(timeout=60)
        self.sender = sender
        self.recipient = recipient
        self.amount = amount
        self.sender_balance = sender_balance
        self.done = False
        self._interaction = original_interaction

    async def _finish(self, interaction: discord.Interaction, confirmed: bool):
        if self.done:
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass
            return
        self.done = True
        self.clear_items()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass

        if confirmed:
            db = interaction.client.db
            gid = interaction.guild.id
            if not await db.spend_yuan(gid, self.sender.id, self.amount):
                user = await db.get_user(gid, self.sender.id)
                embed = discord.Embed(color=0x8B0000, title="TRANSFER DENIED", description="中华人民共和国社会信用局")
                embed.add_field(name="REASON", value=f"Insufficient funds. Balance: ¥{user['yuan']:,} · Required: ¥{self.amount:,}", inline=False)
                await interaction.edit_original_response(embed=embed, view=self)
                return

            await db.adjust_yuan(gid, self.recipient.id, self.amount)
            recipient_data = await db.get_user(gid, self.recipient.id)
            sender_new = self.sender_balance - self.amount
            recipient_new = recipient_data["yuan"]

            ack = discord.Embed(color=0x2d7a2d, title="TRANSFER PROCESSED", description="中华人民共和国社会信用局")
            ack.add_field(name="OUTCOME", value=f"¥{self.amount:,} dispatched to {self.recipient.mention}.", inline=False)
            await interaction.edit_original_response(embed=ack, view=self)

            public = discord.Embed(color=0x2d7a2d, title="YUAN TRANSFER RECORDED", description="中华人民共和国社会信用局")
            public.add_field(name="FROM", value=self.sender.mention, inline=True)
            public.add_field(name="TO", value=self.recipient.mention, inline=True)
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

            bot = interaction.client
            transfers = await db.increment_counter(self.sender.id, "transfers_completed")
            await check_milestone(bot, interaction.guild, self.sender, "transfers_completed", transfers, channel=interaction.channel)
            if self.amount >= 50_000:
                large_transfers = await db.increment_counter(self.sender.id, "large_transfers_made")
                await check_milestone(bot, interaction.guild, self.sender, "large_transfers_made", large_transfers, channel=interaction.channel)
            return
        else:
            embed = discord.Embed(color=0x888888, title="TRANSFER VOIDED", description="中华人民共和国社会信用局")
            embed.add_field(name="OUTCOME", value="Transaction cancelled by sender.", inline=False)
            await interaction.edit_original_response(embed=embed, view=self)

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
        for item in self.children:
            item.disabled = True
        try:
            await self._interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass


class RequestView(discord.ui.View):
    def __init__(self, requester: discord.Member, target: discord.Member, amount: int):
        super().__init__(timeout=300)
        self.requester = requester
        self.target = target
        self.amount = amount
        self.done = False
        self.message = None

    async def _finish(self, interaction: discord.Interaction, accepted: bool):
        if self.done:
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass
            return
        self.done = True
        self.clear_items()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass

        if accepted:
            db = interaction.client.db
            gid = interaction.guild.id
            if not await db.spend_yuan(gid, self.target.id, self.amount):
                user = await db.get_user(gid, self.target.id)
                embed = discord.Embed(color=0x8B0000, title="REQUEST FAILED", description="中华人民共和国社会信用局")
                embed.set_thumbnail(url=_TREASURY_THUMBNAIL)
                embed.add_field(name="REASON", value=f"Insufficient funds. {self.target.mention} has ¥{user['yuan']:,} · Required: ¥{self.amount:,}", inline=False)
                await interaction.edit_original_response(embed=embed, view=self)
                return

            await db.adjust_yuan(gid, self.requester.id, self.amount)
            target_data, requester_data = await asyncio.gather(
                db.get_user(gid, self.target.id),
                db.get_user(gid, self.requester.id),
            )
            target_new = target_data["yuan"]
            requester_new = requester_data["yuan"]

            embed = discord.Embed(color=0x2d7a2d, title="REQUEST FULFILLED", description="中华人民共和国社会信用局")
            embed.set_thumbnail(url=_TREASURY_THUMBNAIL)
            embed.add_field(name="PAYER", value=self.target.mention, inline=True)
            embed.add_field(name="RECIPIENT", value=self.requester.mention, inline=True)
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

            bot = interaction.client
            transfers = await db.increment_counter(self.target.id, "transfers_completed")
            await check_milestone(bot, interaction.guild, self.target, "transfers_completed", transfers, channel=interaction.channel)
            if self.amount >= 50_000:
                large_transfers = await db.increment_counter(self.target.id, "large_transfers_made")
                await check_milestone(bot, interaction.guild, self.target, "large_transfers_made", large_transfers, channel=interaction.channel)
        else:
            embed = discord.Embed(color=0x888888, title="REQUEST DECLINED", description="中华人民共和国社会信用局")
            embed.set_thumbnail(url=_TREASURY_THUMBNAIL)
            embed.add_field(name="OUTCOME", value=f"{self.target.mention} declined the request of ¥{self.amount:,}.", inline=False)
            embed.timestamp = discord.utils.utcnow()

        await interaction.edit_original_response(embed=embed, view=self)

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
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class BattleView(discord.ui.View):
    def __init__(self, bot: commands.Bot, challenger: discord.Member, opponent: discord.Member, amount: int, guild_id: int):
        super().__init__(timeout=300)
        self.bot = bot
        self.challenger = challenger
        self.opponent = opponent
        self.amount = amount
        self.guild_id = guild_id
        self.done = False
        self.message = None

    async def _refund_challenger(self):
        await self.bot.db.adjust_yuan(self.guild_id, self.challenger.id, self.amount)

    async def _finish(self, interaction: discord.Interaction, accepted: bool):
        if self.done:
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass
            return
        self.done = True
        self.clear_items()
        try:
            await interaction.response.defer()
        except discord.HTTPException:
            pass

        db = interaction.client.db
        gid = self.guild_id

        if not accepted:
            await self._refund_challenger()
            embed = discord.Embed(color=0x888888, title="ARBITRATION DECLINED", description="中华人民共和国社会信用局")
            embed.add_field(name="OUTCOME", value=f"Defendant declined. Stake of ¥{self.amount:,} returned to {self.challenger.mention}.", inline=False)
            await interaction.edit_original_response(embed=embed, view=self)
            return

        if not await db.spend_yuan(gid, self.opponent.id, self.amount):
            await self._refund_challenger()
            opponent_data = await db.get_user(gid, self.opponent.id)
            embed = discord.Embed(color=0x8B0000, title="ARBITRATION VOIDED", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value=f"Defendant has insufficient funds. Balance: ¥{opponent_data['yuan']:,} · Required: ¥{self.amount:,}", inline=False)
            embed.add_field(name="OUTCOME", value=f"Stake returned to {self.challenger.mention}.", inline=False)
            await interaction.edit_original_response(embed=embed, view=self)
            return

        winner, loser = random.choice([(self.challenger, self.opponent), (self.opponent, self.challenger)])
        payout = self.amount * 2
        await db.adjust_yuan(gid, winner.id, payout)

        embed = discord.Embed(color=0x2d7a2d, title="ARBITRATION RESOLVED", description="中华人民共和国社会信用局")
        embed.add_field(name="PARTIES", value=f"{self.challenger.mention} vs {self.opponent.mention}", inline=False)
        embed.add_field(name="WINNER", value=f"{winner.mention} · +¥{payout:,}", inline=True)
        embed.add_field(name="LOSER", value=f"{loser.mention} · ¥0", inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Accept", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge is not addressed to you.", ephemeral=True)
            return
        await self._finish(interaction, accepted=True)

    @discord.ui.button(label="Decline", style=discord.ButtonStyle.danger)
    async def decline(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.opponent.id:
            await interaction.response.send_message("This challenge is not addressed to you.", ephemeral=True)
            return
        await self._finish(interaction, accepted=False)

    async def on_timeout(self):
        if self.done:
            return
        self.done = True
        try:
            await self._refund_challenger()
        except Exception:
            pass
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                embed = discord.Embed(color=0x888888, title="ARBITRATION EXPIRED", description="中华人民共和国社会信用局")
                embed.add_field(name="OUTCOME", value=f"No response received. Stake of ¥{self.amount:,} returned to {self.challenger.mention}.", inline=False)
                await self.message.edit(embed=embed, view=self)
            except discord.HTTPException:
                pass


class Economy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db
        self._buy_handlers = {
            "report":              self._buy_report,
            "denounce":            self._buy_denounce,

            "rehabilitate":        self._buy_rehabilitate,
            "appeal":              self._buy_appeal,
            "exception":           self._buy_exception,
            "reeducation":         self._buy_reeducation,
            "lottery_dono":        self._buy_lottery_dono,
            "model_citizen":       self._buy_model_citizen,
            "dispute":             self._buy_dispute,
            "investigation":       self._buy_investigation,
            "protection":          self._buy_protection,
            "inquiry":             self._buy_inquiry,
            "criticism":           self._buy_criticism,
            "legal_rep":           self._buy_legal_rep,
            "anon_identity":       self._buy_anon_identity,
            "immunity":            self._buy_immunity,
            "media_coverage":      self._buy_media_coverage,
            "gacha_slots":         self._buy_gacha_upgrade,
            "gacha_rolls":         self._buy_gacha_upgrade,
            "gacha_spawn":         self._buy_gacha_upgrade,
        }

    def _post_score(self, interaction: discord.Interaction, member: discord.Member, old: float, new: float):
        self.bot.dispatch("score_change", interaction.guild, member, interaction.channel, old, new)

    async def _buyer_author(self, embed: discord.Embed, interaction: discord.Interaction, gid: int):
        name = await self.bot.format_user_full(interaction.user, gid)
        embed.set_author(name=name, icon_url=interaction.user.display_avatar.url)

    @app_commands.command(name="shop", description="Browse the Social Credit Bureau's shop")
    async def shop(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)
        uid = interaction.user.id
        gid = interaction.guild.id
        tier_vals = await asyncio.gather(*(
            self.db.get_counter(uid, f"gacha:upgrade:{gid}:{GACHA_UPGRADE_TIERS[iid]['key']}")
            for iid in GACHA_UPGRADE_TIERS
        ))
        gacha_tiers = {iid: int(v or 0) for iid, v in zip(GACHA_UPGRADE_TIERS, tier_vals)}
        embeds = await _build_shop_embeds(username=str(interaction.user), db=self.db, user_id=uid, guild_id=gid, _gacha_tiers=gacha_tiers)
        items_for_cat = _build_items_for_cat()
        view = ShopView(embeds, items_for_cat, gacha_tiers, self, active="core")
        await interaction.followup.send(
            embed=embeds["core"],
            view=view,
            file=discord.File("images/market.png", filename="market.png"),
        )

    @app_commands.command(name="yuan", description="View a citizen's Yuan balance")
    @app_commands.describe(citizen="Citizen to look up (defaults to yourself)")
    async def yuan(self, interaction: discord.Interaction, citizen: discord.Member = None):
        await interaction.response.defer()
        target = citizen or interaction.user
        user = await self.db.get_user(interaction.guild.id, target.id)
        embed = discord.Embed(color=0xCC0000, title="TREASURY RECORD", description="中华人民共和国社会信用局")
        embed.set_author(name=await self.bot.format_user_full(target, interaction.guild.id), icon_url=target.display_avatar.url)
        embed.add_field(name="BALANCE",      value=f"¥{user['yuan']:,}",              inline=True)
        embed.add_field(name="TOTAL EARNED", value=f"¥{user['total_yuan_earned']:,}", inline=True)
        embed.add_field(name="TOTAL SPENT",  value=f"¥{user['total_yuan_spent']:,}",  inline=True)
        await interaction.followup.send(embed=embed)

    @app_commands.command(name="battle", description="Challenge a citizen to a 50/50 Yuan duel")
    @app_commands.describe(opponent="Citizen to challenge", amount="Yuan stake (each side risks this much)")
    async def battle(self, interaction: discord.Interaction, opponent: discord.Member, amount: app_commands.Range[int, 1000, None]):
        await interaction.response.defer()
        gid = interaction.guild.id
        challenger = interaction.user

        if opponent.id == challenger.id or opponent.bot:
            await interaction.followup.send("Invalid opponent.", ephemeral=True)
            return

        if not await self.db.spend_yuan(gid, challenger.id, amount):
            user = await self.db.get_user(gid, challenger.id)
            await interaction.followup.send(
                f"Insufficient funds. Balance: ¥{user['yuan']:,} · Required: ¥{amount:,}", ephemeral=True
            )
            return

        expiry = int(discord.utils.utcnow().timestamp()) + 300
        view = BattleView(self.bot, challenger, opponent, amount, gid)
        embed = discord.Embed(color=0xCC0000, title="ARBITRATION REQUEST", description="中华人民共和国社会信用局")
        embed.add_field(name="CHALLENGER", value=challenger.mention, inline=True)
        embed.add_field(name="DEFENDANT", value=opponent.mention, inline=True)
        embed.add_field(name="STAKE", value=f"¥{amount:,} each · Winner takes ¥{amount * 2:,}", inline=False)
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=False)
        embed.timestamp = discord.utils.utcnow()
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg

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

        await interaction.response.defer(ephemeral=item not in _PUBLIC_ITEMS)
        await self._execute_buy(interaction, item, target, text)

    async def _execute_buy(
        self,
        interaction: discord.Interaction,
        item: str,
        target: discord.Member = None,
        text: str = None,
    ):
        cfg = SHOP_ITEMS[item]
        gid = interaction.guild.id
        uid = interaction.user.id

        if item == "protection" and target and await self.db.get_effect(gid, target.id, "protection"):
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
                owned = await self.db.get_cosmetic_badges(uid)
                if item in owned:
                    await interaction.followup.send("You already have this cosmetic.", ephemeral=True)
                    return

        cost = cfg["cost"]
        if item == "rehabilitate":
            rehab_count = await self.db.get_rehabilitation_count(gid, uid)
            cost = cfg["cost"] * (2 ** rehab_count)

        if item in GACHA_UPGRADE_TIERS:
            meta = GACHA_UPGRADE_TIERS[item]
            tier = int(await self.db.get_counter(uid, f"gacha:upgrade:{gid}:{meta['key']}") or 0)
            max_tiers = len(meta["costs"])
            if tier >= max_tiers:
                await interaction.followup.send(
                    f"**{cfg['name']}** is already at max tier ({max_tiers}/{max_tiers}).", ephemeral=True
                )
                return
            cost = meta["costs"][tier]

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
        purchases = await self.db.increment_counter(uid, "purchases_made")
        await check_milestone(self.bot, interaction.guild, interaction.user, "purchases_made", purchases, channel=interaction.channel)
        await self._dispatch(interaction, item, cfg, target, text, cost)

    async def _dispatch(self, interaction, item_id, cfg, target, text, cost):
        gid = interaction.guild.id
        uid = interaction.user.id
        if item_id in _LOTTERY_TIERS:
            await self._buy_lottery(interaction, gid, uid, cfg, target, text, cost, item_id)
            return
        if item_id in GACHA_UPGRADE_TIERS:
            await self._buy_gacha_upgrade(interaction, gid, uid, cfg, target, text, cost, item_id)
            return
        handler = self._buy_handlers.get(item_id)
        if handler:
            await handler(interaction, gid, uid, cfg, target, text, cost)
        elif cfg.get("cosmetic"):
            await self._buy_cosmetic(interaction, gid, uid, item_id, cfg, target, text, cost)

    async def _buy_report(self, interaction, gid, uid, cfg, target, text, cost):
        is_anon = await self.db.consume_effect(gid, uid, "anon_identity")
        delta, block = await self.db.apply_defense_chain(gid, target.id, -2.0)
        if block:
            embed = discord.Embed(color=0x888888, title="REPORT NULLIFIED", description="中华人民共和国社会信用局")
            msg = (
                "An Administrative Exception on file absorbed the action."
                if block == "exception" else
                "Citizen Immunity deflected the report."
            )
            embed.add_field(name="OUTCOME", value=msg, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        old, new = await self.db.update_score(gid, target.id, delta, "citizen report")
        await self.db.increment_reported(gid, target.id)
        await self.db.increment_filed_reports(gid, uid)
        report_num = await self.db.increment_report_counter(gid)
        embed = discord.Embed(color=0xCC0000, title="REPORT FILED", description="中华人民共和国社会信用局")
        if not is_anon:
            await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="SCORE IMPACT", value=f"{delta:.2f}", inline=True)
        embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)
        self._post_score(interaction, target, old, new)

    async def _buy_denounce(self, interaction, gid, uid, cfg, target, text, cost):
        is_anon = await self.db.consume_effect(gid, uid, "anon_identity")
        delta, block = await self.db.apply_defense_chain(gid, target.id, -20.0)
        if block:
            embed = discord.Embed(color=0x888888, title="DENOUNCEMENT NULLIFIED", description="中华人民共和国社会信用局")
            msg = (
                "An Administrative Exception on file absorbed the action."
                if block == "exception" else
                "Citizen Immunity deflected the denouncement."
            )
            embed.add_field(name="OUTCOME", value=msg, inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            return
        old, new = await self.db.update_score(gid, target.id, delta, "public denouncement")
        await self.db.increment_reported(gid, target.id)
        report_num = await self.db.increment_report_counter(gid)
        bounty = await self.db.consume_investigation_bounty(gid, target.id)
        if bounty:
            await self.db.adjust_yuan(gid, uid, bounty.get("reward", _INVESTIGATION_BOUNTY_REWARD))
        embed = discord.Embed(color=0xCC0000, title="PUBLIC DENOUNCEMENT FILED", description="中华人民共和国社会信用局")
        if not is_anon:
            await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="SCORE IMPACT", value=f"{delta:.2f}", inline=True)
        embed.add_field(name="STATED CRIME", value=text[:100], inline=False)
        if bounty:
            embed.add_field(name="INVESTIGATION BOUNTY CLAIMED", value=f"+¥{bounty.get('reward', _INVESTIGATION_BOUNTY_REWARD):,}", inline=False)
        embed.set_footer(text=f"Report #{report_num:05d} · GLORY TO THE CCP!")
        embed.timestamp = discord.utils.utcnow()
        await interaction.channel.send(embed=embed)
        await interaction.followup.send("Denouncement has been filed.", ephemeral=True)
        self._post_score(interaction, target, old, new)

        distinct_targets = await self.db.count_distinct_denounce_targets(gid, uid)
        if distinct_targets >= 5:
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "serial_denouncer", channel=interaction.channel)
        distinct_denouncers = await self.db.count_distinct_denouncers(gid, target.id)
        if distinct_denouncers >= 5:
            await unlock_achievement(self.bot, interaction.guild, target, "frequently_denounced", channel=interaction.channel)


    async def _buy_rehabilitate(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        old, new = await self.db.update_score(gid, recipient.id, 3.0, "rehabilitation certificate")
        if target:
            embed = discord.Embed(color=0xFFD700, title="REHABILITATION PROGRAMME GIFTED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="RECIPIENT", value=target.mention, inline=True)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0xFFD700, title="REHABILITATION APPROVED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
        self._post_score(interaction, recipient, old, new)

    async def _buy_appeal(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, recipient.id, "appeal", expires_at)
        if target:
            embed = discord.Embed(color=0x1a3a5c, title="APPEAL FILED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="RECIPIENT", value=target.mention, inline=True)
            embed.add_field(name="EFFECT", value="Next incoming penalty within 12 hours reduced by 50%. Single use.", inline=False)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0x1a3a5c, title="APPEAL FILED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="EFFECT", value="The next negative score action against this citizen within 12 hours will be reduced by 50%. Single use.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_exception(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, recipient.id, "exception", expires_at)
        if target:
            embed = discord.Embed(color=0x2d7a2d, title="ADMINISTRATIVE EXCEPTION GRANTED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="RECIPIENT", value=target.mention, inline=True)
            embed.add_field(name="EFFECT", value="Next negative score action within 24 hours will be completely nullified. Single use.", inline=False)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0x2d7a2d, title="ADMINISTRATIVE EXCEPTION GRANTED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="EFFECT", value="The next negative score action against this citizen within 24 hours will be completely nullified. Single use.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_reeducation(self, interaction, gid, uid, cfg, target, text, cost):
        if await self.db.get_effect(gid, target.id, "freeze"):
            await interaction.followup.send(f"{target.mention} is already score-frozen.", ephemeral=True)
            return
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, target.id, "freeze", expires_at)
        await self.db.invalidate_effect_cache(gid, target.id, "freeze")
        embed = discord.Embed(color=0x8B0000, title="RE-EDUCATION SENTENCE ISSUED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="DURATION", value="Score frozen for 2 hours by order of the Bureau.", inline=False)
        await interaction.followup.send(embed=embed)

    async def _buy_lottery(self, interaction, gid, uid, cfg, target, text, cost, item_id):
        tier = _LOTTERY_TIERS[item_id]
        recipient = target if target else interaction.user
        gifted = target is not None
        roll = random.random()
        gift_line = f" -> {recipient.mention}" if gifted else ""
        if roll < 0.7:
            net = 0 if gifted else -cost
            embed = discord.Embed(
                color=0x555555,
                title="🎰  YOU LOST!",
                description=f"{interaction.user.mention}{gift_line} · **-¥{cost:,}**",
            )
            await self.db.update_lottery_stats(gid, recipient.id, False, net)
            await self._check_lottery_addict(interaction.guild, recipient, interaction.channel)
        elif roll < 0.9:
            winnings = random.randint(*tier["win"])
            net = winnings if gifted else winnings - cost
            await self.db.adjust_yuan(gid, recipient.id, winnings)
            embed = discord.Embed(
                color=0xFFD700,
                title="🎰  YOU WON!",
                description=f"{interaction.user.mention}{gift_line} · **+¥{winnings:,}** · net {net:+,}",
            )
            embed.set_footer(text="/vote on top.gg for bonus Yuan and score · GLORY TO THE CCP!")
            await self.db.update_lottery_stats(gid, recipient.id, True, net)
        else:
            winnings = random.randint(*tier["jackpot"])
            net = winnings if gifted else winnings - cost
            await self.db.adjust_yuan(gid, recipient.id, winnings)
            embed = discord.Embed(
                color=0xFF4444,
                title="🎰  JACKPOT.",
                description=f"{interaction.user.mention}{gift_line} · **+¥{winnings:,}** · net {net:+,}",
            )
            embed.set_footer(text="/vote on top.gg for bonus Yuan and score · GLORY TO THE CCP!")
            await self.db.update_lottery_stats(gid, recipient.id, True, net)
            await unlock_achievement(self.bot, interaction.guild, recipient, "jackpot_winner", channel=interaction.channel)
        await self._buyer_author(embed, interaction, gid)
        await interaction.followup.send(embed=embed)

    async def _check_lottery_addict(self, guild, user, channel):
        row = await self.db.get_user(guild.id, user.id)
        if not row:
            return
        net = int(row.get("lottery_net", 0))
        if net <= -100_000:
            await unlock_achievement(self.bot, guild, user, "lottery_addict", channel=channel)
        if net <= -500_000:
            await unlock_achievement(self.bot, guild, user, "high_roller_loss", channel=channel)

    async def _buy_lottery_dono(self, interaction, gid, uid, cfg, target, text, cost):
        user_row = await self.db.get_user(gid, uid)
        balance  = int(user_row["yuan"]) if user_row else 0
        if balance <= 0:
            await interaction.followup.send("You have no yuan to wager.", ephemeral=True)
            return
        won = random.random() < 0.5
        if won:
            await self.db.adjust_yuan(gid, uid, balance)
            await self.db.update_lottery_stats(gid, uid, True, balance)
            embed = discord.Embed(
                color=0xFFD700,
                title="WIN  ·  ALL-IN REPORT",
                description=f"¥{balance:,} -> ¥{balance * 2:,}",
            )
        else:
            await self.db.spend_yuan(gid, uid, balance)
            await self.db.update_lottery_stats(gid, uid, False, -balance)
            await self._check_lottery_addict(interaction.guild, interaction.user, interaction.channel)
            embed = discord.Embed(
                color=0x111111,
                title="LOSS  ·  ALL-IN REPORT",
                description=f"¥{balance:,} -> ¥0",
            )
        embed.timestamp = discord.utils.utcnow()
        await self._buyer_author(embed, interaction, gid)
        await interaction.followup.send(embed=embed)

    async def _buy_model_citizen(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        last = await self.db.get_last_self_action_time(gid, uid, "model_citizen")
        if last and (time.time() - last) < 3600:
            remaining = int(3600 - (time.time() - last))
            m, s = divmod(remaining, 60)
            embed = discord.Embed(color=0x888888, title="COMMENDATION DENIED", description="中华人民共和国社会信用局")
            embed.add_field(name="REASON", value=f"This commendation channel is not yet available. Retry in {m}m {s}s.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)
            await self.db.adjust_yuan(gid, uid, cost)
            return
        old, new = await self.db.update_score(gid, recipient.id, 2.0, "model citizen commendation")
        if target:
            embed = discord.Embed(color=0xFFD700, title="MODEL CITIZEN COMMENDATION", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="NOMINEE", value=target.mention, inline=True)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Commendation has been filed.", ephemeral=True)
        else:
            embed = discord.Embed(color=0xFFD700, title="MODEL CITIZEN COMMENDATION", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)
        self._post_score(interaction, recipient, old, new)

    async def _buy_dispute(self, interaction, gid, uid, cfg, target, text, cost):
        buyer_wins = random.random() < 0.5
        winner = interaction.user if buyer_wins else target
        loser  = target if buyer_wins else interaction.user
        w_old, w_new = await self.db.update_score(gid, winner.id,  5.0, "dispute resolution victory")
        loser_delta, _ = await self.db.apply_defense_chain(gid, loser.id, -5.0)
        l_old, l_new = await self.db.update_score(gid, loser.id,  loser_delta, "dispute resolution loss")
        defendant_name  = await self.bot.format_user_full(target, gid)
        winner_name     = await self.bot.format_user_full(winner, gid)
        loser_name      = await self.bot.format_user_full(loser,  gid)
        embed = discord.Embed(color=0xCC0000, title="DISPUTE RESOLUTION", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="DEFENDANT",  value=defendant_name,  inline=False)
        embed.add_field(name="OUTCOME", value=f"{winner_name} wins +5.00 · {loser_name} loses {loser_delta:.2f}", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)
        self._post_score(interaction, winner, w_old, w_new)
        self._post_score(interaction, loser,  l_old, l_new)

    async def _buy_investigation(self, interaction, gid, uid, cfg, target, text, cost):
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
        bounty_line = f"¥{total_bounty:,} bounty" + (f" (¥{_INVESTIGATION_BOUNTY_REWARD:,} base + ¥{extra_bounty:,} added)" if extra_bounty else "")
        embed = discord.Embed(color=0x8B0000, title="SPECIAL INVESTIGATION OPENED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="BOUNTY", value=bounty_line, inline=False)
        embed.add_field(name="NOTE", value="The next citizen to file a report on this subject will receive the reward.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_protection(self, interaction, gid, uid, cfg, target, text, cost):
        expires_at = int(time.time()) + 315360000
        await self.db.add_effect(gid, target.id, "protection", expires_at)
        embed = discord.Embed(color=0x2d7a2d, title="POLITICAL PROTECTION GRANTED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="EFFECT", value="The first negative action against this citizen will be reduced by 50%. Lasts until triggered.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_inquiry(self, interaction, gid, uid, cfg, target, text, cost):
        attacker_id = await self.db.get_last_attacker(gid, uid)
        embed = discord.Embed(color=0x1a1a2e, title="INTERNAL INQUIRY", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        if attacker_id:
            attacker = interaction.guild.get_member(attacker_id)
            attacker_name = await self.bot.format_user_full(attacker, gid) if attacker else f"User {attacker_id}"
            embed.add_field(name="LAST KNOWN AGGRESSOR", value=attacker_name, inline=False)
        else:
            embed.add_field(name="RESULT", value="No reports or denouncements on file against this citizen.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_criticism(self, interaction, gid, uid, cfg, target, text, cost):
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, target.id, "criticism", expires_at)
        embed = discord.Embed(color=0xCC0000, title="COORDINATED CRITICISM ORDERED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBJECT", value=target.mention, inline=True)
        embed.add_field(name="EFFECT", value="All negative score actions against this citizen deal double loss for 24 hours.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)

    async def _buy_legal_rep(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, recipient.id, "legal_rep", expires_at)
        if target:
            embed = discord.Embed(color=0x1a3a5c, title="LEGAL REPRESENTATION RETAINED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="RECIPIENT", value=target.mention, inline=True)
            embed.add_field(name="EFFECT", value="All negative score actions against this citizen are reduced by 50% for 12 hours.", inline=False)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0x1a3a5c, title="LEGAL REPRESENTATION ACTIVE", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="EFFECT", value="All negative score actions against this citizen are reduced by 50% for 12 hours.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_anon_identity(self, interaction, gid, uid, cfg, target, text, cost):
        expires_at = int(time.time()) + cfg["duration"]
        await self.db.add_effect(gid, uid, "anon_identity", expires_at)
        embed = discord.Embed(color=0x333333, title="ALTERNATE IDENTITY ASSIGNED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="EFFECT", value="The next report or denouncement filed by this citizen will appear as Unknown Citizen. Single use.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_immunity(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        expires_at = int(time.time()) + (86400 * 7)
        await self.db.add_effect(gid, recipient.id, "immunity", expires_at)
        if target:
            embed = discord.Embed(color=0x2d7a2d, title="CITIZEN IMMUNITY GRANTED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="RECIPIENT", value=target.mention, inline=True)
            embed.add_field(name="EFFECT", value="50% chance to completely block the next negative action against this citizen. Single use.", inline=False)
            if text:
                embed.add_field(name="MESSAGE", value=text[:200], inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0x2d7a2d, title="CITIZEN IMMUNITY ACTIVE", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="EFFECT", value="50% chance to completely block the next negative action against this citizen. Single use.", inline=False)
            await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_media_coverage(self, interaction, gid, uid, cfg, target, text, cost):
        recipient = target if target else interaction.user
        old, new = await self.db.update_score(gid, recipient.id, 4.0, "state media coverage")
        if target:
            embed = discord.Embed(color=0xFFD700, title="STATE MEDIA COVERAGE ARRANGED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="SUBJECT", value=target.mention, inline=True)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=True)
            embed.timestamp = discord.utils.utcnow()
            await interaction.channel.send(embed=embed)
            await interaction.followup.send("Gift has been delivered.", ephemeral=True)
        else:
            embed = discord.Embed(color=0xFFD700, title="STATE MEDIA COVERAGE ARRANGED", description="中华人民共和国社会信用局")
            await self._buyer_author(embed, interaction, gid)
            embed.add_field(name="SCORE", value=f"{old:.2f} -> {new:.2f}", inline=False)
            embed.timestamp = discord.utils.utcnow()
            await interaction.followup.send(embed=embed)
        self._post_score(interaction, recipient, old, new)

    async def _buy_gacha_upgrade(self, interaction, gid, uid, cfg, target, text, cost, item_id):
        meta = GACHA_UPGRADE_TIERS[item_id]
        counter_key = f"gacha:upgrade:{gid}:{meta['key']}"
        tier = int(await self.db.get_counter(uid, counter_key) or 0)
        new_tier = tier + 1
        await self.db.set_counter(uid, counter_key, new_tier)
        max_tiers = len(meta["costs"])
        value = meta["values"][new_tier - 1]
        unit = meta["unit"]
        maxed = new_tier >= max_tiers
        next_cost = f"¥{meta['costs'][new_tier]:,}" if not maxed else "MAXED"
        embed = discord.Embed(color=0x576F72, title="BUREAU UPGRADE PROCESSED", description="中华人民共和国社会信用局")
        embed.add_field(name="UPGRADE", value=cfg["name"], inline=True)
        embed.add_field(name="TIER", value=f"{new_tier}/{max_tiers}" + (" · **MAXED**" if maxed else ""), inline=True)
        embed.add_field(name="NEW VALUE", value=f"{value} {unit}", inline=True)
        if not maxed:
            embed.add_field(name="NEXT TIER", value=next_cost, inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _buy_cosmetic(self, interaction, gid, uid, item_id, cfg, target, text, cost):
        meta  = COSMETIC_META.get(item_id, {})
        color = meta.get("color", 0xFFD700)
        label = meta.get("label", item_id.upper())
        note  = meta.get("note", "Your cosmetic status has been recorded in the bureau's registry.")
        if item_id == "eternal_chairman":
            await self.db.add_eternal_chairman(uid)
            self.bot.ec_users.add(uid)
        else:
            await self.db.add_cosmetic_badge(uid, item_id)
        embed = discord.Embed(color=color, title="DISTINCTION CONFERRED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="DISTINCTION", value=label, inline=True)
        embed.add_field(name="NOTE", value=note, inline=False)
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

        expiry = int(discord.utils.utcnow().timestamp()) + 60
        embed = discord.Embed(color=0xCC0000, title="TRANSFER REQUEST", description="中华人民共和国社会信用局")
        embed.set_thumbnail(url=_TREASURY_THUMBNAIL)
        embed.add_field(name="FROM", value=interaction.user.mention, inline=True)
        embed.add_field(name="TO", value=recipient.mention, inline=True)
        embed.add_field(name="AMOUNT", value=f"¥{amount:,}", inline=True)
        embed.add_field(name="BALANCE AFTER", value=f"¥{user['yuan'] - amount:,}", inline=True)
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=True)
        embed.timestamp = discord.utils.utcnow()

        view = TransferView(interaction.user, recipient, amount, user["yuan"], interaction)
        await interaction.followup.send(embed=embed, view=view, file=discord.File("images/treasury.png", filename="treasury.png"), ephemeral=True)

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

        expiry = int(discord.utils.utcnow().timestamp()) + 300
        embed = discord.Embed(color=0xCC0000, title="YUAN REQUEST", description="中华人民共和国社会信用局")
        embed.set_thumbnail(url=_TREASURY_THUMBNAIL)
        embed.add_field(name="FROM", value=citizen.mention, inline=True)
        embed.add_field(name="TO", value=interaction.user.mention, inline=True)
        embed.add_field(name="AMOUNT", value=f"¥{amount:,}", inline=True)
        if reason:
            embed.add_field(name="REASON", value=reason[:200], inline=False)
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=False)
        embed.timestamp = discord.utils.utcnow()

        view = RequestView(interaction.user, citizen, amount)
        msg = await interaction.followup.send(embed=embed, view=view, file=discord.File("images/treasury.png", filename="treasury.png"))
        view.message = msg


    @app_commands.command(name="confess", description="Publicly confess your crimes to the Bureau for a score reprieve")
    @app_commands.describe(text="Your confession (max 200 characters)")
    async def confess(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id

        if len(text) > 200:
            await interaction.followup.send("Confession exceeds 200 characters.", ephemeral=True)
            return

        last_confess = await self.db.get_last_self_action_time(gid, uid, "confess")
        if last_confess and int(time.time()) - last_confess < 3600:
            remaining = 3600 - (int(time.time()) - last_confess)
            minutes = remaining // 60
            await interaction.followup.send(
                f"Confession cooldown active. You may confess again in {minutes}m.",
                ephemeral=True,
            )
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

        embed = discord.Embed(color=0xCC0000, title="SELF-CRITICISM RECEIVED", description="中华人民共和国社会信用局")
        await self._buyer_author(embed, interaction, gid)
        embed.add_field(name="SUBMISSION", value=text[:200], inline=False)
        embed.add_field(name="VERDICT", value=f"Sentence reduced. +{new - old:.2f} credit rating applied.", inline=True)
        embed.add_field(name="COST", value=f"¥{cost:,}", inline=True)
        embed.add_field(name="NOTE", value="This submission has been added to the permanent record.", inline=False)
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed)
        self._post_score(interaction, interaction.user, old, new)
        await unlock_achievement(self.bot, interaction.guild, interaction.user, "first_confession", channel=interaction.channel)
        confessions = await self.db.increment_counter(uid, "confessions_made")
        await check_milestone(self.bot, interaction.guild, interaction.user, "confessions_made", confessions, channel=interaction.channel)

    @buy.autocomplete("item")
    async def item_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        uid = interaction.user.id
        gid = interaction.guild_id
        tier_vals = await asyncio.gather(*(
            self.db.get_counter(uid, f"gacha:upgrade:{gid}:{GACHA_UPGRADE_TIERS[iid]['key']}")
            for iid in GACHA_UPGRADE_TIERS
        ))
        gacha_tiers = {iid: int(v or 0) for iid, v in zip(GACHA_UPGRADE_TIERS, tier_vals)}

        choices = []
        for k, v in SHOP_ITEMS.items():
            if not (current.lower() in k or current.lower() in v["name"].lower()):
                continue
            if k in GACHA_UPGRADE_TIERS:
                meta = GACHA_UPGRADE_TIERS[k]
                tier = gacha_tiers[k]
                max_tier = len(meta["costs"])
                cost_str = "MAXED" if tier >= max_tier else f"¥{meta['costs'][tier]:,}"
            else:
                cost_str = f"¥{v['cost']:,}"
            choices.append(app_commands.Choice(name=f"{v['name']} · {cost_str}", value=k))
        return choices[:25]


async def setup(bot: commands.Bot):
    await bot.add_cog(Economy(bot))
