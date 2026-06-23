import os
import discord
from discord.ext import commands
from dotenv import load_dotenv

load_dotenv()

SUPPORT_URL = "https://discord.gg/invite/k4W6YAPYhC"

intents = discord.Intents.default()
intents.message_content = True
client = commands.Bot(command_prefix="ccp ", intents=intents)

@client.event
async def on_ready():
    await client.change_presence(
        status=discord.Status.dnd,
        activity=discord.CustomActivity(name="Maintenance | ccp support"),
    )
    print(f"Logged in as {client.user} — maintenance mode active")

@client.command(name="support")
async def support(ctx):
    await ctx.send(f"Undergoing Maintenance. Join the support server for updates: {SUPPORT_URL}")

client.run(os.getenv("DISCORD_TOKEN"))
