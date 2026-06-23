import time
import discord
from discord.ext import commands, tasks
from cogs.achievements import unlock as unlock_achievement

THUMBS_UP = "👍"
THUMBS_DOWN = "👎"


class PropagandaScheduler(commands.Cog):
    """Background close/conclude loop for propaganda events.

    No app_commands or prefix commands live here, so this cog is safe to load
    only on the singleton scheduler process (RUN_MODE=scheduler) without ever
    risking duplicate command handling on gateway worker processes.
    """

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

        if member:
            await unlock_achievement(self.bot, guild, member, "propaganda_winner", channel=channel)


async def setup(bot: commands.Bot):
    await bot.add_cog(PropagandaScheduler(bot))
