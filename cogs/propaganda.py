import time
import discord
from discord import app_commands
from discord.ext import commands
from config.banned_topics import get_banned_match
from cogs.achievements import unlock as unlock_achievement


class Propaganda(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    propaganda_group = app_commands.Group(name="propaganda", description="Propaganda event commands")

    @propaganda_group.command(name="start", description="Start a propaganda submission event (mod only)")
    @app_commands.describe(
        submit_channel="Channel where citizens submit their propaganda",
        reveal_channel="Channel where submissions are revealed and voted on",
        duration_hours="How long submissions are open (in hours)",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def propaganda_start(
        self,
        interaction: discord.Interaction,
        submit_channel: discord.TextChannel,
        reveal_channel: discord.TextChannel,
        duration_hours: int,
    ):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id

        existing = await self.db.get_open_propaganda_event(gid)
        if existing:
            await interaction.followup.send(
                "An event is already open for submissions. It must close before a new one can start.",
                ephemeral=True,
            )
            return

        closes_at = int(time.time()) + (duration_hours * 3600)
        event_id = await self.db.create_propaganda_event(
            gid, interaction.user.id, submit_channel.id, reveal_channel.id, closes_at
        )

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 宣传活动")
        embed.add_field(name="EVENT OPENED", value=f"Event #{event_id}", inline=False)
        embed.add_field(name="SUBMIT IN", value=submit_channel.mention, inline=True)
        embed.add_field(name="REVEALED IN", value=reveal_channel.mention, inline=True)
        embed.add_field(name="CLOSES", value=f"<t:{closes_at}:R>", inline=False)
        embed.add_field(
            name="INSTRUCTIONS",
            value=f"Citizens may submit their propaganda using `/propaganda submit` in {submit_channel.mention}.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()

        await submit_channel.send(embed=embed)
        await interaction.followup.send(f"Propaganda event #{event_id} started.", ephemeral=True)

    @propaganda_group.command(name="submit", description="Submit your propaganda for the active event")
    @app_commands.describe(text="Your propaganda submission (max 280 characters)")
    async def propaganda_submit(self, interaction: discord.Interaction, text: str):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        uid = interaction.user.id

        if len(text) > 280:
            await interaction.followup.send("Submission exceeds 280 characters.", ephemeral=True)
            return

        event = await self.db.get_open_propaganda_event(gid)
        if not event:
            await interaction.followup.send("There is no active propaganda event in this server.", ephemeral=True)
            return

        if await self.db.is_propaganda_banned(event["id"], uid):
            await interaction.followup.send(
                "You are banned from this event for submitting counter-revolutionary content. You may participate in future events.",
                ephemeral=True,
            )
            return

        if await self.db.get_propaganda_submission_by_user(event["id"], uid):
            await interaction.followup.send("You have already submitted to this event.", ephemeral=True)
            return

        match = get_banned_match(text)
        if match:
            await self.db.ban_from_propaganda_event(event["id"], gid, uid, match)
            penalty, _ = await self.db.apply_defense_chain(gid, uid, -5.0)
            old, new = await self.db.update_score(gid, uid, penalty, "counter-revolutionary propaganda submission")
            await interaction.followup.send(
                f"Your submission contains banned content: `{match}`\n\n"
                f"You have been banned from this event but may participate in future events.\n"
                f"**{penalty:.2f}** social credit has been deducted.",
                ephemeral=True,
            )
            self.bot.dispatch("score_change", interaction.guild, interaction.user, interaction.channel, old, new)
            await unlock_achievement(self.bot, interaction.guild, interaction.user, "propaganda_banned", channel=interaction.channel)
            return

        await self.db.add_propaganda_submission(event["id"], gid, uid, text)

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 宣传活动")
        embed.add_field(
            name="SUBMISSION RECORDED",
            value="Your propaganda has been received and will be revealed when the event closes.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Propaganda(bot))
