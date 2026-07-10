import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

SUPPORT_URL = "https://discord.gg/invite/k4W6YAPYhC"

MAINTENANCE_MSG = f"The bot is currently undergoing maintenance. Join the support server for updates: {SUPPORT_URL}"

intents = discord.Intents.default()
intents.message_content = True

class MaintenanceTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        await interaction.response.send_message(MAINTENANCE_MSG, ephemeral=True)
        return False

client = commands.Bot(command_prefix="ccp ", intents=intents, tree_cls=MaintenanceTree)

@client.event
async def on_ready():
    await client.change_presence(
        status=discord.Status.dnd,
        activity=discord.CustomActivity(name="Maintenance | ccp support"),
    )
    print(f"Logged in as {client.user} - maintenance mode active")

@client.command(name="support")
async def support(ctx):
    await ctx.send(MAINTENANCE_MSG)

@client.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        await ctx.send(MAINTENANCE_MSG)

client.run(os.getenv("DISCORD_TOKEN"))
