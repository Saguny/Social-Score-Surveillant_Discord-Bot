import discord
from discord import app_commands
from discord.ext import commands

from config.shop import COSMETIC_META


def _display_name(badge_id: str) -> str:
    meta = COSMETIC_META.get(badge_id)
    if meta:
        return meta.get("label", badge_id)
    return badge_id.lstrip(" |").strip()


class BadgesCog(commands.Cog, name="Badges"):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    badge = app_commands.Group(name="badge", description="Choose which badge to display next to your name")

    @badge.command(name="select", description="Choose which badge to display next to your name")
    @app_commands.describe(choice="The badge to display")
    async def select(self, interaction: discord.Interaction, choice: str):
        await interaction.response.defer()
        owned = set(await self.db.get_cosmetic_badges(interaction.user.id))
        if choice not in owned:
            await interaction.followup.send("You do not own that badge.", ephemeral=True)
            return
        await self.db.set_badge_preference(interaction.user.id, choice)
        await interaction.followup.send(
            f"{interaction.user.mention} is now displaying **{_display_name(choice)}**."
        )

    @select.autocomplete("choice")
    async def select_autocomplete(self, interaction: discord.Interaction, current: str):
        owned = await self.db.get_cosmetic_badges(interaction.user.id)
        choices = []
        for badge_id in owned:
            name = _display_name(badge_id)
            if current.lower() in name.lower():
                choices.append(app_commands.Choice(name=name, value=badge_id))
        return choices[:25]

    @badge.command(name="clear", description="Revert to the bureau's automatic badge priority")
    async def clear(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.db.clear_badge_preference(interaction.user.id)
        await interaction.followup.send(
            "Badge preference cleared. The bureau will choose for you.", ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(BadgesCog(bot))
