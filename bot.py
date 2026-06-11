import os
import sys
import asyncio
from datetime import datetime, timezone
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database.db import Database

_orig_embed_init = discord.Embed.__init__

def _embed_init(self, **kwargs):
    _orig_embed_init(self, **kwargs)
    self.set_footer(text="GLORY TO THE CCP!")

discord.Embed.__init__ = _embed_init

load_dotenv()

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

HELP_TEXT = """
Console commands:
  sync                        Sync slash commands globally
  reload <cog>                Reload a cog (e.g. cogs.scoring)
  guilds                      List all guilds
  force_reset <gid> <uid>     Reset a user's score to 750
  db_reset <gid>              Wipe all data for a guild
  web                         Start web dashboard and open browser
  restart  (or r)             Restart the bot
  shutdown (or q)             Shut down the bot
  help                        Show this message
"""


async def console_loop(bot: commands.Bot):
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
        except Exception:
            break
        line = line.strip()
        if not line:
            continue
        parts = line.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("r", "restart"):
            print("Restarting...")
            await bot.close()
            os._exit(42)

        elif cmd in ("q", "shutdown"):
            print("Shutting down...")
            await bot.close()

        elif cmd == "sync":
            await bot.tree.sync()
            print("Slash commands synced.")

        elif cmd == "reload":
            if not args:
                print("Usage: reload <cog>")
                continue
            try:
                await bot.reload_extension(args[0])
                print(f"{args[0]} reloaded.")
            except Exception as e:
                print(f"Failed: {e}")

        elif cmd == "guilds":
            for g in bot.guilds:
                print(f"{g.id}  {g.name}  ({g.member_count} members)")

        elif cmd == "force_reset":
            if len(args) < 2:
                print("Usage: force_reset <guild_id> <user_id>")
                continue
            try:
                gid, uid = int(args[0]), int(args[1])
                user = await bot.db.get_user(gid, uid)
                delta = 750.0 - user["score"]
                await bot.db.update_score(gid, uid, delta, "owner force reset")
                print(f"User {uid} in guild {gid} reset to 750.")
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == "db_reset":
            if not args:
                print("Usage: db_reset <guild_id>")
                continue
            try:
                gid = int(args[0])
                await bot.db.reset_guild_db(gid)
                print(f"Guild {gid} wiped.")
            except Exception as e:
                print(f"Error: {e}")

        elif cmd == "web":
            from web.server import start_web_server
            asyncio.create_task(start_web_server(bot))

        elif cmd == "help":
            print(HELP_TEXT)

        else:
            print(f"Unknown command: {cmd}. Type 'help' for a list.")


class SocialCreditBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="ccp ", intents=intents)
        self.db = Database()

    async def close(self):
        await self.db.stop_flush_task()
        await super().close()

    async def setup_hook(self):
        await self.db.init()
        self.db.start_flush_task()
        await self.load_extension("cogs.scoring")
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.stats")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.social")
        await self.load_extension("cogs.fundraiser")
        await self.load_extension("cogs.guide")
        await self.load_extension("cogs.posters")
        await self.tree.sync()
        print("Slash commands synced.")
        from web.server import start_web_server
        asyncio.create_task(start_web_server(self))
        self.loop.create_task(console_loop(self))

    async def on_ready(self):
        self.start_time = datetime.now(timezone.utc)
        for guild in self.guilds:
            member_ids = [m.id for m in guild.members if not m.bot]
            await self.db.register_guild_members(guild.id, member_ids)
        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="/guide"
        ))
        print(f"Online: {self.user}  |  Guilds: {len(self.guilds)}")
        print("Type 'help' for console commands.")

    async def on_guild_join(self, guild: discord.Guild):
        member_ids = [m.id for m in guild.members if not m.bot]
        await self.db.register_guild_members(guild.id, member_ids)
        print(f"Joined {guild.name} · registered {len(member_ids)} members.")

    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            await self.db.register_user(member.guild.id, member.id)


bot = SocialCreditBot()
bot.run(os.getenv("DISCORD_TOKEN"))
