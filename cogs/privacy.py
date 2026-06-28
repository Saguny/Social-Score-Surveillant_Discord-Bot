import discord
from discord import app_commands
from discord.ext import commands

CONFIRM_TIMEOUT = 60
_BUREAU_IMG = "images/security.png"


def _bureau_file():
    return discord.File(_BUREAU_IMG)


class OptOutConfirmView(discord.ui.View):
    def __init__(self, user_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.user_id = user_id
        self.done = False
        self._original_interaction = original_interaction

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
            await interaction.client.db.opt_out_user(self.user_id)
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · OPT-OUT CONFIRMED")
            embed.add_field(
                name="STATUS",
                value=(
                    "You have been removed from the Bureau's records. Every row of data tied to your "
                    "Discord ID has been permanently deleted across every server. Your messages will no "
                    "longer be scored and you can no longer interact with the bot, aside from `/optin`."
                ),
                inline=False,
            )
        else:
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · OPT-OUT CANCELLED")
            embed.add_field(name="STATUS", value="No changes were made. You remain a registered citizen.", inline=False)
        embed.set_thumbnail(url="attachment://security.png")
        await interaction.edit_original_response(embed=embed, view=self, attachments=[_bureau_file()])

    @discord.ui.button(label="Yes, opt out", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True)

    @discord.ui.button(label="No, cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._original_interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass


class OptInConfirmView(discord.ui.View):
    def __init__(self, user_id: int, original_interaction: discord.Interaction):
        super().__init__(timeout=CONFIRM_TIMEOUT)
        self.user_id = user_id
        self.done = False
        self._original_interaction = original_interaction

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
            await interaction.client.db.opt_in_user(self.user_id)
            embed = discord.Embed(color=0x2d5a27, title="中华人民共和国社会信用局 · OPT-IN CONFIRMED")
            embed.add_field(
                name="STATUS",
                value="Welcome back, citizen. You are re-registered as a brand new account, starting from scratch.",
                inline=False,
            )
        else:
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · OPT-IN CANCELLED")
            embed.add_field(name="STATUS", value="No changes were made. You remain opted out.", inline=False)
        embed.set_thumbnail(url="attachment://security.png")
        await interaction.edit_original_response(embed=embed, view=self, attachments=[_bureau_file()])

    @discord.ui.button(label="Yes, opt in", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, True)

    @discord.ui.button(label="No, cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._finish(interaction, False)

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        try:
            await self._original_interaction.edit_original_response(view=self)
        except discord.HTTPException:
            pass


class Privacy(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="optout", description="Permanently opt out of the Social Credit System and delete your data")
    async def optout(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if await self.db.is_opted_out(interaction.user.id):
            await interaction.followup.send("You are already opted out. Use `/optin` to rejoin.", ephemeral=True)
            return

        expiry = int(discord.utils.utcnow().timestamp()) + CONFIRM_TIMEOUT
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CONFIRM OPT-OUT")
        embed.add_field(
            name="ARE YOU SURE?",
            value=(
                "This will permanently delete every row of data tied to your Discord ID across every server "
                "the Bureau operates in: score, yuan, transaction history, achievements, badges, fundraiser "
                "activity, stock portfolios, vote history, and everything else. Your messages will stop being "
                "scored immediately and you will be unable to use any bot command except `/optin`. "
                "This cannot be undone once confirmed; running `/optin` afterward starts you over from scratch."
            ),
            inline=False,
        )
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=False)
        embed.set_thumbnail(url="attachment://security.png")
        await interaction.followup.send(
            embed=embed,
            view=OptOutConfirmView(interaction.user.id, interaction),
            file=_bureau_file(),
            ephemeral=True,
        )

    @app_commands.command(name="optin", description="Opt back in to the Social Credit System")
    async def optin(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await self.db.is_opted_out(interaction.user.id):
            await interaction.followup.send("You are not opted out.", ephemeral=True)
            return

        expiry = int(discord.utils.utcnow().timestamp()) + CONFIRM_TIMEOUT
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CONFIRM OPT-IN")
        embed.add_field(
            name="ARE YOU SURE?",
            value=(
                "This will re-register you with the Bureau across every server the bot is in. Since your "
                "prior data was permanently deleted when you opted out, you will start fresh at the default "
                "score and zero yuan, as a brand new citizen."
            ),
            inline=False,
        )
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=False)
        embed.set_thumbnail(url="attachment://security.png")
        await interaction.followup.send(
            embed=embed,
            view=OptInConfirmView(interaction.user.id, interaction),
            file=_bureau_file(),
            ephemeral=True,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(Privacy(bot))
