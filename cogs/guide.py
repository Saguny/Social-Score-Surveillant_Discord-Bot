import discord
from discord import app_commands
from discord.ext import commands
from config.ranks import RANKS


class Guide(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="guide", description="Full guide to the Social Credit System")
    async def guide(self, interaction: discord.Interaction):
        embeds = []

        e1 = discord.Embed(color=0xCC0000, title="中华人民共和国社会信用局 · CITIZEN GUIDE")
        e1.description = (
            "Your social credit score is tracked silently. Every message you send is evaluated. "
            "Score changes accumulate slowly over time. Rank changes trigger an official bureau notification.\n\n"
            "Score range: 600 (floor) to 1300 (ceiling). Everyone starts at 750."
        )
        rank_lines = "\n".join(f"{r['min']} to {r['max']}   {r['name']}" for r in RANKS)
        e1.add_field(name="RANKS", value=f"```\n{rank_lines}\n```", inline=False)
        embeds.append(e1)

        e2 = discord.Embed(color=0xCC0000, title="SCORING RULES")
        e2.add_field(
            name="SENTIMENT",
            value=(
                "Each message is analyzed for tone. Positive messages nudge your score up, "
                "negative ones nudge it down. Max impact per message is +0.2 or -0.2. "
                "Neutral messages do nothing."
            ),
            inline=False,
        )
        e2.add_field(
            name="STRUCTURAL VIOLATIONS",
            value=(
                "Sending the same message twice in a row: -1.0\n"
                "Excessive caps on longer messages: -0.2\n"
                "Messages under 4 characters: -0.1"
            ),
            inline=False,
        )
        e2.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e2)

        e3 = discord.Embed(color=0xCC0000, title="SCORE AND STAT COMMANDS")
        e3.add_field(name="/score [citizen]",        value="View your score and current rank.", inline=False)
        e3.add_field(name="/stats [citizen]",        value="Full breakdown: trends, peak/low score, messages, report history.", inline=False)
        e3.add_field(name="/history [citizen]",      value="Last 5 score changes. Viewing others requires mod permissions.", inline=False)
        e3.add_field(name="/leaderboard",            value="Top 3 most compliant and top 3 greatest threats.", inline=False)
        e3.add_field(name="/state_report",           value="Server-wide report: biggest rise/fall, top informant, yuan in circulation, avg score.", inline=False)
        embeds.append(e3)

        e4 = discord.Embed(color=0xCC0000, title="YUAN AND ECONOMY")
        e4.add_field(name="Earning Yuan",  value="You earn 1 Yuan per message automatically.", inline=False)
        e4.add_field(name="/yuan",         value="Check your Yuan balance and lifetime earned/spent.", inline=False)
        e4.add_field(name="/shop",         value="Browse available shop items and their costs.", inline=False)
        e4.add_field(
            name="/buy <item> [target] [text]",
            value=(
                "`report` (500) · Dock a citizen 2 score points. Files an official report.\n"
                "`denounce` (1000) · Post a public denouncement with a custom message (100 char max).\n"
                "`surveillance` (300) · Get a DM every time a target's score changes for 24 hours.\n"
                "`rehabilitate` (400+) · Recover 3 score points. Cost doubles each time you use it.\n"
                "`expunge` (600) · Wipe your last 5 score changes from public history.\n"
                "`freeze` (800) · Freeze your score for 1 hour. No changes will be applied.\n"
                "`propaganda` (350) · Bot posts a state-approved commendation of you in the channel."
            ),
            inline=False,
        )
        embeds.append(e4)

        e5 = discord.Embed(color=0xCC0000, title="SOCIAL RATING")
        e5.add_field(
            name="/endorse <citizen> [reason]",
            value="Grant a citizen a positive rating. Adjusts their score by +3.0. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.add_field(
            name="/rebuke <citizen> [reason]",
            value="Issue a negative rating against a citizen. Adjusts their score by -3.0. One use per citizen per 24 hours. Optional reason is displayed in the embed and logged.",
            inline=False,
        )
        e5.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e5)

        e6 = discord.Embed(color=0xCC0000, title="FUNDRAISERS")
        e6.description = (
            "A citizen proposes to do something in exchange for Yuan. Others donate. "
            "When the goal is hit, the organizer must follow through, then open a vote. "
            "If enough citizens confirm, they receive the funds. If enough deny, donors are refunded."
        )
        e6.add_field(name="/fundraise create <goal> <description>", value="Start a fundraiser. Set a Yuan goal and describe what you will do.", inline=False)
        e6.add_field(name="/fundraise donate <id> <amount>",        value="Donate Yuan to an open fundraiser. Cannot donate to your own.", inline=False)
        e6.add_field(name="/fundraise complete <id>",               value="Mark your funded fundraiser as complete. Opens the voting phase.", inline=False)
        e6.add_field(name="/fundraise vote <id> <confirm|deny>",    value="Vote on whether the organizer fulfilled their obligation. One vote per citizen.", inline=False)
        e6.add_field(name="/fundraise list",                        value="List all active fundraisers in this server.", inline=False)
        e6.add_field(name="/fundraise info <id>",                   value="View full details and vote tally for a specific fundraiser.", inline=False)
        embeds.append(e6)

        e7 = discord.Embed(color=0x333333, title="MOD COMMANDS")
        e7.description = "These are prefix commands. Type them directly in chat."
        e7.add_field(name="ccp initialize",                         value="Register all current server members into the system.", inline=False)
        e7.add_field(name="ccp adjust <@citizen> <delta> <reason>", value="Manually adjust a citizen's score by any amount.", inline=False)
        e7.add_field(name="ccp reset <@citizen>",                   value="Reset a citizen back to 750.", inline=False)
        e7.add_field(name="ccp threshold <n>",                      value="Set how many votes are required to resolve a fundraiser. Default is 3.", inline=False)
        e7.add_field(name="ccp webconsent <on|off>",                value="Enable or disable message logging for the web dashboard.", inline=False)
        e7.add_field(name="ccp poster",                              value="Display a random propaganda poster.", inline=False)
        e7.add_field(name="ccp posters",                             value="Toggle daily propaganda poster broadcasts in this channel. React ❤️ for +1 credit and +20 yuan · React 😡 for -1 credit.", inline=False)
        e7.set_footer(text="GLORY TO THE CCP!")
        embeds.append(e7)

        await interaction.response.send_message(embeds=embeds, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(Guide(bot))
