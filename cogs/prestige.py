import discord
from discord import app_commands
from discord.ext import commands
from config.ranks import PRESTIGE_THRESHOLD, STARTING_SCORE


class PrestigeView(discord.ui.View):
    def __init__(self, member: discord.Member, db, bot):
        super().__init__(timeout=60)
        self.member = member
        self.db = db
        self.bot = bot
        self.done = False
        self.message = None

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

        if not confirmed:
            embed = discord.Embed(color=0x333333, title="中华人民共和国社会信用局 · 晋升")
            embed.add_field(name="PRESTIGE CANCELLED", value="You remain at your current standing.", inline=False)
            await interaction.edit_original_response(embed=embed, view=self)
            return

        gid = interaction.guild.id
        uid = self.member.id
        user = await self.db.get_user(gid, uid)

        if user["score"] < PRESTIGE_THRESHOLD:
            embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 晋升")
            embed.add_field(
                name="PRESTIGE FAILED",
                value=f"Score dropped below {PRESTIGE_THRESHOLD:.2f} before confirmation.",
                inline=False,
            )
            await interaction.edit_original_response(embed=embed, view=self)
            return

        old_yuan = user["yuan"]
        old_score, new_score = await self.db.update_score(gid, uid, STARTING_SCORE - user["score"], "prestige reset")
        await self.db.set_yuan(gid, uid, 0)
        level = await self.db.increment_counter(uid, "prestige_level")

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 晋升")
        embed.add_field(name="PRESTIGE ACHIEVED", value=f"{self.member.mention} has prestiged to level {level}.", inline=False)
        embed.add_field(name="SCORE", value=f"{old_score:.2f} -> {new_score:.2f}", inline=True)
        embed.add_field(name="YUAN", value=f"¥{old_yuan:,} -> ¥0", inline=True)
        embed.timestamp = discord.utils.utcnow()
        await interaction.edit_original_response(embed=embed, view=self)
        self.bot.dispatch("score_change", interaction.guild, self.member, interaction.channel, old_score, new_score)

    @discord.ui.button(label="Confirm", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This is not your prestige confirmation.", ephemeral=True)
            return
        await self._finish(interaction, confirmed=True)

    @discord.ui.button(label="Nevermind", style=discord.ButtonStyle.danger)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.member.id:
            await interaction.response.send_message("This is not your prestige confirmation.", ephemeral=True)
            return
        await self._finish(interaction, confirmed=False)

    async def on_timeout(self):
        self.done = True
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass


class Prestige(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    @app_commands.command(name="prestige", description="Reset your score and yuan in this server for permanent prestige")
    async def prestige(self, interaction: discord.Interaction):
        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id
        user = await self.db.get_user(gid, uid)

        if user["score"] < PRESTIGE_THRESHOLD:
            await interaction.followup.send(
                f"Prestige requires a score of at least {PRESTIGE_THRESHOLD:.2f} in this server. Current score: {user['score']:.2f}",
                ephemeral=True,
            )
            return

        expiry = int(discord.utils.utcnow().timestamp()) + 60
        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 晋升")
        embed.add_field(
            name="PRESTIGE AVAILABLE",
            value=(
                f"Your score ({user['score']:.2f}) has reached the threshold for prestige.\n"
                f"Confirming will reset your score to {STARTING_SCORE:.2f} and your yuan to ¥0 in this server, "
                "and permanently raise your prestige level everywhere."
            ),
            inline=False,
        )
        embed.add_field(name="EXPIRES", value=f"<t:{expiry}:R>", inline=False)
        view = PrestigeView(interaction.user, self.db, self.bot)
        msg = await interaction.followup.send(embed=embed, view=view)
        view.message = msg


async def setup(bot: commands.Bot):
    await bot.add_cog(Prestige(bot))
