import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from config.shop import COSMETIC_META


def _display_name(badge_id: str) -> str:
    meta = COSMETIC_META.get(badge_id)
    if meta:
        return meta.get("label", badge_id)
    return badge_id.lstrip(" |").strip()


def _badge_suffix(badge_id: str) -> str:
    meta = COSMETIC_META.get(badge_id)
    return meta["suffix"] if meta else badge_id


def _build_preview_embed(user: discord.abc.User, owned: list[str], active_pref: str | None) -> discord.Embed:
    username = user.display_name
    lines = []
    for badge_id in owned:
        suffix = _badge_suffix(badge_id)
        marker = " ◄" if badge_id == active_pref else ""
        lines.append(f"{username} {suffix}{marker}")
    embed = discord.Embed(color=0xFFD700, title="BADGE REGISTRY", description="中华人民共和国社会信用局")
    embed.set_author(name=user.display_name, icon_url=user.display_avatar.url)
    embed.add_field(name="YOUR DECORATIONS", value="\n".join(lines), inline=False)
    return embed


class BadgePreviewView(discord.ui.View):
    def __init__(self, user: discord.abc.User, owned: list[str], current_pref: str | None, db):
        super().__init__(timeout=120)
        self.user = user
        self.owned = owned
        self.db = db
        self._add_select(current_pref)

    def _add_select(self, active_pref: str | None):
        self.clear_items()
        options = [
            discord.SelectOption(
                label=_display_name(b)[:100],
                value=b,
                default=b == active_pref,
            )
            for b in self.owned
        ]
        sel = discord.ui.Select(placeholder="Equip a badge...", options=options[:25])
        sel.callback = self._make_select_cb()
        self.add_item(sel)

    def _make_select_cb(self):
        view = self

        async def callback(interaction: discord.Interaction):
            if interaction.user.id != view.user.id:
                await interaction.response.send_message("This is not your badge menu.", ephemeral=True)
                return
            choice = interaction.data["values"][0]
            await view.db.set_badge_preference(interaction.user.id, choice)
            view._add_select(choice)
            embed = _build_preview_embed(interaction.user, view.owned, choice)
            try:
                await interaction.response.defer()
            except discord.HTTPException:
                pass
            await interaction.edit_original_response(embed=embed, view=view)

        return callback


class BadgesCog(commands.Cog, name="Badges"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    badge = app_commands.Group(name="badge", description="Choose which badge to display next to your name")

    @badge.command(name="select", description="Choose which badge to display next to your name")
    @app_commands.describe(choice="The badge to display")
    async def select(self, interaction: discord.Interaction, choice: str):
        await interaction.response.defer()
        owned = set(await self.db.get_cosmetic_badges(interaction.user.id, permanent_only=True))
        if choice not in owned:
            await interaction.followup.send("You do not own that badge.", ephemeral=True)
            return
        await self.db.set_badge_preference(interaction.user.id, choice)
        await interaction.followup.send(
            f"{interaction.user.mention} is now displaying **{_display_name(choice)}**."
        )

    @select.autocomplete("choice")
    async def select_autocomplete(self, interaction: discord.Interaction, current: str):
        owned = await self.db.get_cosmetic_badges(interaction.user.id, permanent_only=True)
        choices = []
        for badge_id in owned:
            name = _display_name(badge_id)
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=badge_id))
        return choices[:25]

    @badge.command(name="preview", description="Preview all your badges and equip one from the dropdown")
    async def preview(self, interaction: discord.Interaction):
        await interaction.response.defer()
        uid = interaction.user.id
        owned, pref = await asyncio.gather(
            self.db.get_cosmetic_badges(uid, permanent_only=True),
            self.db.get_badge_preference(uid),
        )
        if not owned:
            await interaction.followup.send("You have no badges to preview.", ephemeral=True)
            return
        embed = _build_preview_embed(interaction.user, owned, pref)
        view = BadgePreviewView(interaction.user, owned, pref, self.db)
        await interaction.followup.send(embed=embed, view=view)

    @badge.command(name="clear", description="Revert to the bureau's automatic badge priority")
    async def clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.db.clear_badge_preference(interaction.user.id)
        await interaction.followup.send(
            "Badge preference cleared. The bureau will choose for you.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BadgesCog(bot))
