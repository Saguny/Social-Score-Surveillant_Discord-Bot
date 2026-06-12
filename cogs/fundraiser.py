import discord
from discord import app_commands
from discord.ext import commands


def progress_bar(raised: int, goal: int) -> str:
    progress = min(raised / goal, 1.0) if goal > 0 else 0
    filled = int(progress * 10)
    return "█" * filled + "░" * (10 - filled) + f"  ¥{raised} / ¥{goal}"


def fundraiser_embed(fr, guild: discord.Guild, threshold: int) -> discord.Embed:
    creator = guild.get_member(fr["creator_id"])
    creator_name = creator.display_name if creator else "Unknown"
    status_colors = {
        "open":      0xCC0000,
        "funded":    0xFFD700,
        "voting":    0xFF8800,
        "completed": 0x00AA00,
        "refunded":  0x555555,
    }
    color = status_colors.get(fr["status"], 0xCC0000)

    embed = discord.Embed(color=color, title="中华人民共和国社会信用局 · 公民募资")
    embed.add_field(name="FUNDRAISER", value=f"#{fr['id']}", inline=True)
    embed.add_field(name="ORGANIZER", value=creator_name, inline=True)
    embed.add_field(name="STATUS", value=fr["status"].upper(), inline=True)
    embed.add_field(name="OBJECTIVE", value=fr["description"], inline=False)
    embed.add_field(
        name="PROGRESS",
        value=progress_bar(fr["raised"], fr["goal"]),
        inline=False,
    )
    if fr["status"] == "voting":
        embed.add_field(
            name="VERIFICATION",
            value=f"Use `/fundraise vote {fr['id']} confirm` or `deny`\nThreshold: {threshold} votes",
            inline=False,
        )
    embed.set_footer(text=f"Fundraiser #{fr['id']} · GLORY TO THE CCP!")
    return embed


class Fundraiser(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    fundraise = app_commands.Group(name="fundraise", description="Fundraiser commands")

    @fundraise.command(name="create", description="Start a new fundraiser")
    @app_commands.describe(goal="Yuan goal", description="What you will do when funded")
    async def create(self, interaction: discord.Interaction, goal: int, description: str):
        if goal <= 0:
            await interaction.response.send_message("Goal must be greater than 0.", ephemeral=True)
            return

        await interaction.response.defer()
        gid = interaction.guild.id
        fid = await self.db.create_fundraiser(gid, interaction.user.id, description, goal)
        fr = await self.db.get_fundraiser(fid)
        threshold = await self.db.get_confirm_threshold(gid)

        embed = fundraiser_embed(fr, interaction.guild, threshold)
        msg = await interaction.followup.send(embed=embed, wait=True)
        await self.db.set_fundraiser_message(fid, interaction.channel.id, msg.id)

    async def _choices(self, guild_id: int, current: str, statuses: list[str]) -> list[app_commands.Choice]:
        fundraisers = await self.db.get_active_fundraisers(guild_id)
        return [
            app_commands.Choice(
                name=f"#{fr['id']} [{fr['status'].upper()}] {fr['description'][:50]}",
                value=fr["id"],
            )
            for fr in fundraisers
            if fr["status"] in statuses
            and (current == "" or current in str(fr["id"]) or current.lower() in fr["description"].lower())
        ][:25]

    @fundraise.command(name="donate", description="Donate Yuan to a fundraiser")
    @app_commands.describe(fundraiser_id="Fundraiser ID", amount="Amount to donate")
    async def donate(self, interaction: discord.Interaction, fundraiser_id: int, amount: int):
        if amount <= 0:
            await interaction.response.send_message("Amount must be greater than 0.", ephemeral=True)
            return

        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id

        fr = await self.db.get_fundraiser(fundraiser_id)
        if not fr or fr["guild_id"] != gid:
            await interaction.followup.send("Fundraiser not found.", ephemeral=True)
            return
        if fr["status"] != "open":
            await interaction.followup.send(
                f"This fundraiser is not accepting donations (status: {fr['status']}).", ephemeral=True
            )
            return
        if fr["creator_id"] == uid:
            await interaction.followup.send("You cannot donate to your own fundraiser.", ephemeral=True)
            return

        if not await self.db.spend_yuan(gid, uid, amount):
            balance = (await self.db.get_user(gid, uid))["yuan"]
            await interaction.followup.send(f"Insufficient funds. Balance: ¥{balance}", ephemeral=True)
            return

        remaining = fr["goal"] - fr["raised"]
        new_raised = await self.db.donate_to_fundraiser(fundraiser_id, gid, uid, amount)
        fr = await self.db.get_fundraiser(fundraiser_id)

        embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 公民捐款")
        embed.add_field(name="DONOR", value=interaction.user.mention, inline=True)
        embed.add_field(name="AMOUNT", value=f"¥{amount}", inline=True)
        if amount > remaining:
            embed.add_field(name="OVERSHOT THE GOAL BY", value=f"¥{amount - remaining}", inline=True)
        embed.add_field(name="FUNDRAISER", value=f"#{fundraiser_id} · {fr['description']}", inline=False)
        embed.add_field(name="PROGRESS", value=progress_bar(new_raised, fr["goal"]), inline=False)
        await interaction.followup.send(embed=embed)

        if new_raised >= fr["goal"] and fr["status"] == "open":
            await self.db.update_fundraiser_status(fundraiser_id, "funded")
            creator = interaction.guild.get_member(fr["creator_id"])

            funded_embed = discord.Embed(color=0xFFD700, title="中华人民共和国社会信用局 · 目标达成")
            funded_embed.add_field(
                name="FUNDRAISER FUNDED",
                value=f"#{fundraiser_id} · {fr['description']}",
                inline=False,
            )
            funded_embed.add_field(
                name="NOTICE",
                value=(
                    f"{creator.mention if creator else 'Organizer'} · your fundraiser has reached its goal.\n"
                    f"Complete your obligation and use `/fundraise complete {fundraiser_id}` to open verification."
                ),
                inline=False,
            )
            await interaction.channel.send(embed=funded_embed)

    @fundraise.command(name="complete", description="Mark your fundraiser as complete and open voting")
    @app_commands.describe(fundraiser_id="Fundraiser ID")
    async def complete(self, interaction: discord.Interaction, fundraiser_id: int):
        await interaction.response.defer(ephemeral=True)
        gid = interaction.guild.id
        fr = await self.db.get_fundraiser(fundraiser_id)

        if not fr or fr["guild_id"] != gid:
            await interaction.followup.send("Fundraiser not found.", ephemeral=True)
            return
        if fr["creator_id"] != interaction.user.id:
            await interaction.followup.send("Only the fundraiser organizer can do this.", ephemeral=True)
            return
        if fr["status"] != "funded":
            await interaction.followup.send(
                f"Fundraiser must be in 'funded' status. Current: {fr['status']}", ephemeral=True
            )
            return

        await self.db.update_fundraiser_status(fundraiser_id, "voting")
        threshold = await self.db.get_confirm_threshold(gid)
        fr = await self.db.get_fundraiser(fundraiser_id)

        embed = discord.Embed(color=0xFF8800, title="中华人民共和国社会信用局 · 公民验证")
        embed.add_field(name="VERIFICATION OPEN", value=f"Fundraiser #{fundraiser_id}", inline=False)
        embed.add_field(name="CLAIM", value=fr["description"], inline=False)
        embed.add_field(
            name="HOW TO VOTE",
            value=f"`/fundraise vote {fundraiser_id} confirm` · they did it\n`/fundraise vote {fundraiser_id} deny` · they didn't",
            inline=False,
        )
        embed.add_field(name="THRESHOLD", value=f"{threshold} votes required to resolve", inline=False)
        embed.set_footer(text="GLORY TO THE CCP!")
        await interaction.followup.send(embed=embed)

    @fundraise.command(name="vote", description="Vote on a completed fundraiser")
    @app_commands.describe(fundraiser_id="Fundraiser ID", verdict="confirm or deny")
    @app_commands.choices(verdict=[
        app_commands.Choice(name="Confirm · they did it", value="confirm"),
        app_commands.Choice(name="Deny · they didn't", value="deny"),
    ])
    async def vote(self, interaction: discord.Interaction, fundraiser_id: int, verdict: str):
        await interaction.response.defer()
        gid = interaction.guild.id
        uid = interaction.user.id

        fr = await self.db.get_fundraiser(fundraiser_id)
        if not fr or fr["guild_id"] != gid:
            await interaction.followup.send("Fundraiser not found.", ephemeral=True)
            return
        if fr["status"] != "voting":
            await interaction.followup.send("This fundraiser is not in the voting phase.", ephemeral=True)
            return
        if fr["creator_id"] == uid:
            await interaction.followup.send("You cannot vote on your own fundraiser.", ephemeral=True)
            return

        added = await self.db.add_fundraiser_vote(fundraiser_id, uid, verdict)
        if not added:
            await interaction.followup.send("You have already voted on this fundraiser.", ephemeral=True)
            return

        votes = await self.db.get_fundraiser_votes(fundraiser_id)
        confirms = sum(1 for v in votes if v["vote"] == "confirm")
        denies   = sum(1 for v in votes if v["vote"] == "deny")
        threshold = await self.db.get_confirm_threshold(gid)

        embed = discord.Embed(color=0xFF8800, title="中华人民共和国社会信用局")
        embed.add_field(name="VOTE RECORDED", value=f"Fundraiser #{fundraiser_id} · {verdict.upper()}", inline=False)
        embed.add_field(name="CONFIRMS", value=str(confirms), inline=True)
        embed.add_field(name="DENIES",   value=str(denies),   inline=True)
        embed.add_field(name="NEEDED",   value=str(threshold), inline=True)
        await interaction.followup.send(embed=embed)

        if confirms >= threshold:
            await self._resolve(interaction, fr, fundraiser_id, "completed", threshold)
        elif denies >= threshold:
            await self._resolve(interaction, fr, fundraiser_id, "refunded", threshold)

    async def _resolve(self, interaction, fr, fundraiser_id: int, outcome: str, threshold: int):
        gid = fr["guild_id"]
        await self.db.update_fundraiser_status(fundraiser_id, outcome)
        creator = interaction.guild.get_member(fr["creator_id"])

        if outcome == "completed":
            await self.db.add_yuan(gid, fr["creator_id"], fr["goal"])
            color = 0x00AA00
            title = "募资完成  ·  FUNDRAISER COMPLETED"
            body = (
                f"{creator.mention if creator else 'Organizer'} has been awarded ¥{fr['goal']}.\n"
                f"The bureau thanks all citizens for their participation."
            )
        else:
            await self.db.refund_fundraiser(fundraiser_id)
            color = 0x555555
            title = "募资否决  ·  FUNDRAISER DENIED"
            body = (
                f"The obligation was not fulfilled. All donations have been refunded.\n"
                f"This incident has been noted in the bureau's records."
            )

        embed = discord.Embed(color=color, title="中华人民共和国社会信用局")
        embed.add_field(name=title, value=body, inline=False)
        embed.add_field(name="FUNDRAISER", value=f"#{fundraiser_id} · {fr['description']}", inline=False)
        embed.set_footer(text=f"Resolved by {threshold} votes · GLORY TO THE CCP!")
        embed.timestamp = discord.utils.utcnow()
        await interaction.channel.send(embed=embed)

    @fundraise.command(name="list", description="List active fundraisers in this server")
    async def list_fundraisers(self, interaction: discord.Interaction):
        await interaction.response.defer()
        fundraisers = await self.db.get_active_fundraisers(interaction.guild.id)
        if not fundraisers:
            await interaction.followup.send("No active fundraisers.", ephemeral=True)
            return

        embed = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · 活跃募资")
        for fr in fundraisers[:10]:
            creator = interaction.guild.get_member(fr["creator_id"])
            name = creator.display_name if creator else "Unknown"
            embed.add_field(
                name=f"#{fr['id']} · {fr['status'].upper()}",
                value=f"{fr['description']}\n{progress_bar(fr['raised'], fr['goal'])} · by {name}",
                inline=False,
            )
        await interaction.followup.send(embed=embed)

    @fundraise.command(name="info", description="View details of a specific fundraiser")
    @app_commands.describe(fundraiser_id="Fundraiser ID")
    async def info(self, interaction: discord.Interaction, fundraiser_id: int):
        await interaction.response.defer()
        fr = await self.db.get_fundraiser(fundraiser_id)
        if not fr or fr["guild_id"] != interaction.guild.id:
            await interaction.followup.send("Fundraiser not found.", ephemeral=True)
            return

        threshold = await self.db.get_confirm_threshold(interaction.guild.id)
        embed = fundraiser_embed(fr, interaction.guild, threshold)

        if fr["status"] == "voting":
            votes = await self.db.get_fundraiser_votes(fundraiser_id)
            confirms = sum(1 for v in votes if v["vote"] == "confirm")
            denies   = sum(1 for v in votes if v["vote"] == "deny")
            embed.add_field(name="VOTES", value=f"✓ {confirms}  ✗ {denies}  (need {threshold})", inline=False)

        donations = await self.db.get_fundraiser_donations(fundraiser_id)
        if donations:
            totals: dict[int, int] = {}
            for d in donations:
                totals[d["donor_id"]] = totals.get(d["donor_id"], 0) + d["amount"]
            top3 = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:3]
            lines = []
            for i, (donor_id, total) in enumerate(top3, 1):
                member = interaction.guild.get_member(donor_id)
                name = member.display_name if member else "Unknown"
                lines.append(f"{i}. {name} · ¥{total}")
            embed.add_field(name="TOP DONORS", value="\n".join(lines), inline=False)

        await interaction.followup.send(embed=embed)

    @donate.autocomplete("fundraiser_id")
    async def donate_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
        return await self._choices(interaction.guild.id, current, ["open"])

    @complete.autocomplete("fundraiser_id")
    async def complete_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
        fundraisers = await self.db.get_active_fundraisers(interaction.guild.id)
        return [
            app_commands.Choice(
                name=f"#{fr['id']} [{fr['status'].upper()}] {fr['description'][:50]}",
                value=fr["id"],
            )
            for fr in fundraisers
            if fr["status"] == "funded" and fr["creator_id"] == interaction.user.id
            and (current == "" or current in str(fr["id"]) or current.lower() in fr["description"].lower())
        ][:25]

    @vote.autocomplete("fundraiser_id")
    async def vote_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
        return await self._choices(interaction.guild.id, current, ["voting"])

    @info.autocomplete("fundraiser_id")
    async def info_ac(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice]:
        return await self._choices(interaction.guild.id, current, ["open", "funded", "voting", "completed", "refunded"])


async def setup(bot: commands.Bot):
    await bot.add_cog(Fundraiser(bot))
