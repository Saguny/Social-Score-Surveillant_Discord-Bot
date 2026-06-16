import time
import discord
from discord import app_commands
from discord.ext import commands, tasks
from config.banned_topics import get_banned_match

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"


class Propaganda(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self._event_loop.start()

    async def cog_unload(self):
        self._event_loop.cancel()

    @tasks.loop(minutes=5)
    async def _event_loop(self):
        now = int(time.time())
        await self._process_closings(now)
        await self._process_conclusions(now)

    @_event_loop.before_loop
    async def _before_loop(self):
        await self.bot.wait_until_ready()

    async def _process_closings(self, now):
        for event in await self.db.get_propaganda_events_ready_to_close(now):
            await self._close_event(event)

    async def _close_event(self, event):
        guild = self.bot.get_guild(event["guild_id"])
        channel = guild.get_channel(event["reveal_channel_id"]) if guild else None

        if not guild or not channel:
            await self.db.set_propaganda_event_status(event["id"], "concluded")
            return

        submissions = await self.db.get_propaganda_submissions(event["id"])

        if not submissions:
            await self.db.set_propaganda_event_status(event["id"], "concluded")
            embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 宣传活动")
            embed.add_field(name="EVENT CONCLUDED", value="No submissions were received. The people remain silent.", inline=False)
            await channel.send(embed=embed)
            return

        header = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 宣传竞赛")
        header.add_field(
            name="SUBMISSIONS NOW OPEN FOR REVIEW",
            value=f"{len(submissions)} submission(s) received. React with {THUMBS_UP} to approve or {THUMBS_DOWN} to condemn. Voting closes in 24 hours.",
            inline=False,
        )
        await channel.send(embed=header)

        for sub in submissions:
            member = guild.get_member(sub["user_id"])
            name = member.display_name if member else "Unknown Citizen"
            embed = discord.Embed(color=0xFFD700, description=f'"{sub["content"]}"')
            embed.set_author(name=name)
            embed.timestamp = discord.utils.utcnow()
            msg = await channel.send(embed=embed)
            await msg.add_reaction(THUMBS_UP)
            await msg.add_reaction(THUMBS_DOWN)
            await self.db.set_submission_reveal_message(sub["id"], msg.id)

        await self.db.set_propaganda_event_status(event["id"], "voting")

    async def _process_conclusions(self, now):
        for event in await self.db.get_propaganda_events_ready_to_conclude(now):
            await self._conclude_event(event)

    async def _conclude_event(self, event):
        guild = self.bot.get_guild(event["guild_id"])
        channel = guild.get_channel(event["reveal_channel_id"]) if guild else None
        submissions = await self.db.get_propaganda_submissions(event["id"])

        winner = None
        best_votes = -1

        for sub in submissions:
            if not sub["reveal_message_id"] or not channel:
                continue
            try:
                msg = await channel.fetch_message(sub["reveal_message_id"])
                votes = sum(r.count - 1 for r in msg.reactions if str(r.emoji) == THUMBS_UP)
                if votes > best_votes:
                    best_votes = votes
                    winner = sub
            except Exception:
                continue

        await self.db.set_propaganda_event_status(event["id"], "concluded")

        if not winner or not channel:
            return

        await self.db.add_guild_decree(event["guild_id"], winner["user_id"], winner["content"], best_votes)

        member = guild.get_member(winner["user_id"]) if guild else None
        mention = member.mention if member else "Unknown Citizen"

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 宣传胜利者")
        embed.add_field(name="WINNING DECREE", value=f'"{winner["content"]}"', inline=False)
        embed.add_field(name="AUTHOR", value=mention, inline=True)
        embed.add_field(name="APPROVAL VOTES", value=str(best_votes), inline=True)
        embed.add_field(
            name="STATE RECOGNITION",
            value="This decree has been enshrined in the Bureau's official proclamations. It may be issued via `/decree`.",
            inline=False,
        )
        embed.timestamp = discord.utils.utcnow()
        await channel.send(embed=embed)

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
            old, new = await self.db.update_score(gid, uid, -5.0, "counter-revolutionary propaganda submission")
            await interaction.followup.send(
                f"Your submission contains banned content: `{match}`\n\n"
                f"You have been banned from this event but may participate in future events.\n"
                f"**−5.00** social credit has been deducted.",
                ephemeral=True,
            )
            self.bot.dispatch("score_change", interaction.guild, interaction.user, interaction.channel, old, new)
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
