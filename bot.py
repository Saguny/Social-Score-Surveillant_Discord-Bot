import os
import sys
import asyncio
import time
from contextvars import ContextVar
from datetime import datetime, timezone
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database.db import Database
from config.ranks import RANKS

OWNER_ID = 544810950952353823
OWNER_BADGE = " | 𝔻𝕖𝕧𝕖𝕝𝕠𝕡𝕖𝕣 "
OWNER_COLOR = 0xE6E6FA

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

_orig_embed_init = discord.Embed.__init__

def _embed_init(self, **kwargs):
    if _current_user_id.get() == OWNER_ID and "color" not in kwargs and "colour" not in kwargs:
        kwargs["color"] = OWNER_COLOR
    _orig_embed_init(self, **kwargs)
    self.set_footer(text="GLORY TO THE CCP!")

discord.Embed.__init__ = _embed_init


CMD_COOLDOWN = 2.0

_REQUIRED_PERMISSIONS = {
    "send_messages":      "Send Messages",
    "embed_links":        "Embed Links",
    "manage_roles":       "Manage Roles",
    "manage_channels":    "Manage Channels",
    "add_reactions":      "Add Reactions",
    "attach_files":       "Attach Files",
    "read_message_history": "Read Message History",
}

class CreditCommandTree(discord.app_commands.CommandTree):
    async def call(self, interaction: discord.Interaction) -> None:
        _current_user_id.set(interaction.user.id)
        cooldowns: dict[int, float] = self.client._cmd_cooldowns
        now = time.time()
        uid = interaction.user.id
        if uid != OWNER_ID and now - cooldowns.get(uid, 0) < CMD_COOLDOWN:
            await interaction.response.send_message("Slow down, citizen.", ephemeral=True)
            return
        cooldowns[uid] = now
        await super().call(interaction)

    async def on_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        cause = getattr(error, "__cause__", error)
        if isinstance(cause, discord.Forbidden):
            missing = []
            if interaction.guild:
                perms = interaction.guild.me.guild_permissions
                for attr, label in _REQUIRED_PERMISSIONS.items():
                    if not getattr(perms, attr, True):
                        missing.append(label)
            if missing:
                msg = f"Missing permissions: {', '.join(missing)}"
            else:
                msg = "The bot lacks a required permission for this action."
        else:
            print(f"[error] /{getattr(error, 'command', None) and error.command.qualified_name}: {cause!r}")
            msg = "An internal error occurred. Please try again."
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:
            pass

load_dotenv()


def _fullwidth(text: str) -> str:
    out = []
    for ch in text:
        code = ord(ch)
        if 0x21 <= code <= 0x7E:
            out.append(chr(code + 0xFEE0))
        elif ch == ' ':
            out.append('　')
        else:
            out.append(ch)
    return ''.join(out)

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

HELP_TEXT = """
Console commands:
  sync                        Sync slash commands to all guilds
  reload <cog>                Reload a cog (e.g. cogs.scoring)
  guilds                      List all guilds
  force_reset <gid> <uid>     Reset a user's score to 750
  force_yuan <gid> <uid> <n>  Set a user's Yuan balance to n
  db_reset <gid>              Wipe all data for a guild
  web                         Start web dashboard and open browser
  restart  (or r)             Restart the bot
  shutdown (or q)             Shut down the bot
  help                        Show this message
"""


async def _decay_task(bot: commands.Bot):
    while True:
        now = time.time()
        next_run = (int(now) // 86400 + 1) * 86400
        await asyncio.sleep(next_run - now)
        await bot.db.apply_score_decay()
        await bot.db.apply_portfolio_score_bonus()


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
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
            print(f"Slash commands synced to {len(bot.guilds)} guild(s).")

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

        elif cmd == "force_yuan":
            if len(args) < 3:
                print("Usage: force_yuan <guild_id> <user_id> <amount>")
                continue
            try:
                gid, uid, amount = int(args[0]), int(args[1]), int(args[2])
                await bot.db.set_yuan(gid, uid, amount)
                print(f"User {uid} in guild {gid} yuan set to {amount}.")
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
        super().__init__(command_prefix="ccp ", intents=intents, tree_cls=CreditCommandTree)
        self.db = Database()
        self.ec_users: set[int] = set()
        self._cmd_cooldowns: dict[int, float] = {}
        self.start_time = None

    def format_user(self, user) -> str:
        name = str(user)
        if hasattr(user, 'id'):
            if user.id == OWNER_ID:
                return f"{name}{OWNER_BADGE}"
            if user.id in self.ec_users:
                return f"{name} 【{_fullwidth('Winnie the Pooh')}】"
        return name

    async def format_user_full(self, user, guild_id: int) -> str:
        if hasattr(user, 'id'):
            if user.id == OWNER_ID:
                return f"{str(user)}{OWNER_BADGE}"
            if user.id in self.ec_users:
                return f"{str(user)} 【{_fullwidth('Winnie the Pooh')}】"
            from config.shop import COSMETIC_META
            _ORDER = ["voter", "verified", "figure", "influencer", "associate", "asset"]
            badges = await self.db.get_cosmetic_badges(guild_id, user.id)
            badge_set = set(badges)
            for badge_id in reversed(_ORDER):
                if badge_id in badge_set:
                    suffix = COSMETIC_META[badge_id]["suffix"]
                    return f"{str(user)} {suffix}"
        return str(user)

    async def process_commands(self, message: discord.Message) -> None:
        _current_user_id.set(message.author.id)
        uid = message.author.id
        now = time.time()
        if uid != OWNER_ID and now - self._cmd_cooldowns.get(uid, 0) < CMD_COOLDOWN:
            return
        self._cmd_cooldowns[uid] = now
        await super().process_commands(message)

    async def close(self):
        await super().close()

    async def setup_hook(self):
        await self.db.init()
        self.ec_users = await self.db.get_all_eternal_chairmen()
        await self.load_extension("cogs.scoring")
        await self.load_extension("cogs.economy")
        await self.load_extension("cogs.stats")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.social")
        await self.load_extension("cogs.fundraiser")
        await self.load_extension("cogs.guide")
        await self.load_extension("cogs.posters")
        await self.load_extension("cogs.checkin")
        await self.load_extension("cogs.propaganda")
        await self.load_extension("cogs.stocks")
        await self.load_extension("cogs.voting")
        from web.server import start_web_server
        asyncio.create_task(start_web_server(self))
        asyncio.create_task(_decay_task(self))
        self.loop.create_task(console_loop(self))

    async def on_ready(self):
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)
        rank_names = {r["name"] for r in RANKS}
        exec_role_name = "Execution Date: Tomorrow"
        for guild in self.guilds:
            member_ids = [m.id for m in guild.members if not m.bot]
            await self.db.register_guild_members(guild.id, member_ids)
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
            condemned = await self.db.get_condemned_users(guild.id)
            for row in condemned:
                member = guild.get_member(row["user_id"])
                if not member:
                    continue
                already_condemned = False
                try:
                    exec_role = discord.utils.get(guild.roles, name=exec_role_name)
                    if not exec_role:
                        exec_role = await guild.create_role(name=exec_role_name)
                    already_condemned = exec_role in member.roles
                    for rname in rank_names:
                        r = discord.utils.get(guild.roles, name=rname)
                        if r and r in member.roles:
                            await member.remove_roles(r)
                    if not already_condemned:
                        await member.add_roles(exec_role)
                except discord.Forbidden:
                    pass
                confiscated = await self.db.confiscate_yuan(guild.id, row["user_id"])
                exec_channel_id = await self.db.get_execution_channel(guild.id)
                channel = guild.get_channel(exec_channel_id) if exec_channel_id else next(
                    (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None
                )
                if channel and not already_condemned:
                    embed = discord.Embed(color=0x8B0000, title="中华人民共和国社会信用局 · 处决名单")
                    embed.add_field(name="CITIZEN", value=str(member), inline=False)
                    embed.add_field(name="STATUS", value="Placed on the Execution List\nExecution Date: Tomorrow", inline=False)
                    if confiscated > 0:
                        embed.add_field(name="ASSETS CONFISCATED", value=f"¥{confiscated:,} seized and redistributed to the people.", inline=False)
                    embed.timestamp = discord.utils.utcnow()
                    if not exec_channel_id:
                        embed.set_footer(text="Use `ccp executions #channel` to configure a dedicated channel.")
                    try:
                        await channel.send(embed=embed)
                    except discord.Forbidden:
                        pass
        _global_cmds = self.tree.get_commands(guild=None)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()
        for cmd in _global_cmds:
            self.tree.add_command(cmd)

        await self.change_presence(activity=discord.Activity(
            type=discord.ActivityType.watching, name="/guide"
        ))
        print(f"Online: {self.user}  |  Guilds: {len(self.guilds)}  |  Slash commands synced.")
        print("Type 'help' for console commands.")

    async def on_guild_join(self, guild: discord.Guild):
        member_ids = [m.id for m in guild.members if not m.bot]
        await self.db.register_guild_members(guild.id, member_ids)
        await self.db.log_guild_join(guild.id)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"Joined {guild.name} · registered {len(member_ids)} members · slash commands synced.")

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        cause = getattr(error, "__cause__", error)
        if isinstance(cause, discord.Forbidden) or isinstance(error, commands.BotMissingPermissions):
            missing = []
            if ctx.guild:
                perms = ctx.guild.me.guild_permissions
                for attr, label in _REQUIRED_PERMISSIONS.items():
                    if not getattr(perms, attr, True):
                        missing.append(label)
            if missing:
                msg = f"Missing permissions: {', '.join(missing)}"
            else:
                msg = "The bot lacks a required permission for this action."
            try:
                await ctx.send(msg)
            except discord.Forbidden:
                pass
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send("You do not have permission to use this command.")
        elif not isinstance(error, commands.CommandNotFound):
            raise error

    async def on_member_join(self, member: discord.Member):
        if not member.bot:
            await self.db.register_user(member.guild.id, member.id)


bot = SocialCreditBot()
bot.run(os.getenv("DISCORD_TOKEN"))
