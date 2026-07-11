import os
import sys
import json
import asyncio
import random
import time
from contextvars import ContextVar
from datetime import datetime, timezone
import discord
from discord.ext import commands
from dotenv import load_dotenv
from database.db import Database
from config.ranks import RANKS
from infra.run_mode import IS_SCHEDULER, SHARD_COUNT, SHARD_IDS
from infra.redis_client import get_redis
from infra.redis_cache import cache_set, cache_delete
from infra.guild_notify import GUILD_NOTIFY_CHANNEL
from config.privacy import (
    OPTOUT_ALLOWED_SLASH_COMMANDS,
    OPTOUT_ALLOWED_PREFIX_COMMANDS,
    OPTOUT_BLOCKED_MESSAGE,
)
from config.owner import OWNER_ID, OWNER_BADGE

OWNER_COLOR = 0xE6E6FA

_current_user_id: ContextVar[int | None] = ContextVar("current_user_id", default=None)

_orig_embed_init = discord.Embed.__init__

FOOTER_VOTE_NUDGE_CHANCE = 0.35
FOOTER_CHECKIN_NUDGE_CHANCE = 0.15

def _embed_init(self, **kwargs):
    if _current_user_id.get() == OWNER_ID and "color" not in kwargs and "colour" not in kwargs:
        kwargs["color"] = OWNER_COLOR
    _orig_embed_init(self, **kwargs)
    roll = random.random()
    if roll < FOOTER_VOTE_NUDGE_CHANCE:
        self.set_footer(text="/vote for 2x yuan and social credit acquisition")
    elif roll < FOOTER_VOTE_NUDGE_CHANCE + FOOTER_CHECKIN_NUDGE_CHANCE:
        self.set_footer(text="Don't forget to /checkin!")
    else:
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

async def _check_cmd_cooldown(uid: int) -> bool:
    if uid == OWNER_ID:
        return True
    r = get_redis()
    ok = await r.set(f"cmdcd:{uid}", "1", nx=True, ex=int(CMD_COOLDOWN) or 1)
    return bool(ok)


CMD_LOG_MAX = 10
CMD_LOG_TTL = 60 * 86400

# Tracks {interaction_id: (start_time, error_code)} for timing + error correlation
_cmd_timing: dict[int, tuple[float, str | None]] = {}


async def _log_command_usage(guild_id: int | None, user_id: int, command_name: str | None) -> None:
    if guild_id is None or not command_name:
        return
    r = get_redis()
    entry = json.dumps({"command": command_name, "user_id": user_id, "ts": int(time.time())})
    key = f"cmdlog:{guild_id}"
    await r.lpush(key, entry)
    await r.ltrim(key, 0, CMD_LOG_MAX - 1)
    await r.expire(key, CMD_LOG_TTL)


class CreditCommandTree(discord.app_commands.CommandTree):
    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.type != discord.InteractionType.application_command:
            return True
        _current_user_id.set(interaction.user.id)
        if not await _check_cmd_cooldown(interaction.user.id):
            await interaction.response.send_message("Slow down, citizen.", ephemeral=True)
            return False

        # Read command name from raw interaction data (resolved command not available yet)
        data = interaction.data or {}
        pre_name: str | None = data.get('name') or None
        if pre_name:
            for opt in data.get('options', []):
                if opt.get('type') in (1, 2):  # SUB_COMMAND / SUB_COMMAND_GROUP
                    pre_name = f"{pre_name} {opt['name']}"
                    break

        if pre_name not in OPTOUT_ALLOWED_SLASH_COMMANDS:
            if await self.client.db.is_opted_out(interaction.user.id):
                await interaction.response.send_message(OPTOUT_BLOCKED_MESSAGE, ephemeral=True)
                return False

        await _log_command_usage(interaction.guild_id, interaction.user.id, pre_name)
        _cmd_timing[interaction.id] = (time.time(), None)
        return True

    async def on_error(self, interaction: discord.Interaction, error: discord.app_commands.AppCommandError) -> None:
        cause = error.__cause__ or error
        qualified_name = interaction.command.qualified_name if interaction.command else None
        t0, _ = _cmd_timing.pop(interaction.id, (time.time(), None))
        elapsed_ms = int((time.time() - t0) * 1000)
        if interaction.guild_id and qualified_name:
            parts = qualified_name.split(' ', 1)
            asyncio.create_task(
                self.client.db.log_command(
                    interaction.guild_id, interaction.user.id,
                    parts[0], parts[1] if len(parts) > 1 else None,
                    elapsed_ms, False, type(cause).__name__,
                )
            )
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
            qualified_name = interaction.command.qualified_name if interaction.command else None
            print(f"[error] /{qualified_name}: {type(error).__name__}: {cause!r}")
            msg = "An internal error occurred. Please notify us at https://discord.gg/invite/k4W6YAPYhC"
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
  force_score <gid> <uid> <n> Set a user's score to n
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
        await bot.db.snapshot_guild_daily_stats()


_PRESENCE_CYCLE = [
    discord.Activity(type=discord.ActivityType.watching, name="/guide | /shop"),
    discord.Activity(type=discord.ActivityType.watching, name="/vote for 2x boost | /checkin"),
    discord.Activity(type=discord.ActivityType.watching, name="/botinfo | /invite"),
    None,
]


async def _rotate_presence_task(bot: commands.Bot):
    await bot.wait_until_ready()
    while True:
        await asyncio.sleep(300)
        bot._presence_index = (bot._presence_index + 1) % len(_PRESENCE_CYCLE)
        activity = _PRESENCE_CYCLE[bot._presence_index]
        if activity is None:
            treasury_total = await bot.db.get_treasury_total()
            activity = discord.Activity(
                type=discord.ActivityType.watching,
                name=f"¥{treasury_total:,} in the Bureau Treasury",
            )
        await bot.change_presence(activity=activity)


def _fallback_guild_channel(guild: discord.Guild):
    if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
        return guild.system_channel
    return next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)


async def _handle_guild_notify(bot: commands.Bot, guild: discord.Guild, event_type: str, data: dict):
    user_id = data.get("user_id")
    member = guild.get_member(user_id) if user_id is not None else None
    if event_type == "checkin_score_change":
        if member:
            bot.dispatch("score_change", guild, member, _fallback_guild_channel(guild), data.get("old_score"), data.get("new_score"))
    elif event_type == "vote_achievement_check":
        if member:
            from cogs.achievements import unlock as unlock_achievement, check_milestone
            old_score = data.get("old_score")
            new_score = data.get("new_score")
            if old_score is not None and new_score is not None:
                bot.dispatch("score_change", guild, member, _fallback_guild_channel(guild), old_score, new_score)
            await unlock_achievement(bot, guild, member, "first_vote")
            await check_milestone(bot, guild, member, "topgg_votes_total", data.get("total_votes"))
            await check_milestone(bot, guild, member, "topgg_vote_streak", data.get("vote_streak"))
    elif event_type == "achievement_announce":
        if member:
            from cogs.achievements import deliver_achievement_announcements
            await deliver_achievement_announcements(bot.db, guild, member, data.get("ids") or [], data.get("channel_id"))


async def _guild_notify_listener(bot: commands.Bot):
    await bot.wait_until_ready()
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(GUILD_NOTIFY_CHANNEL)
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            payload = json.loads(message["data"])
        except (TypeError, ValueError):
            continue
        event_type = payload.get("event_type")
        if event_type == "reload_gacha":
            cog = bot.get_cog("Gacha")
            if cog:
                try:
                    n = await cog.reload_chars()
                    print(f"[guild-notify] gacha chars reloaded ({n})")
                except Exception as e:
                    print(f"[guild-notify] reload_gacha error: {e!r}")
            continue
        guild = bot.get_guild(payload.get("guild_id"))
        if guild is None:
            continue
        try:
            await _handle_guild_notify(bot, guild, event_type, payload.get("data") or {})
        except Exception as e:
            print(f"[guild-notify] error handling {event_type}: {e!r}")


_GATEWAY_SYNC_CHANNEL = "gateway-sync"


async def _gateway_sync_listener(bot: commands.Bot):
    await bot.wait_until_ready()
    r = get_redis()
    pubsub = r.pubsub()
    await pubsub.subscribe(_GATEWAY_SYNC_CHANNEL)
    async for message in pubsub.listen():
        if message.get("type") != "message":
            continue
        try:
            for guild in bot.guilds:
                bot.tree.copy_global_to(guild=guild)
                await bot.tree.sync(guild=guild)
            print(f"[gateway-sync] synced commands to {len(bot.guilds)} guild(s).")
        except Exception as e:
            print(f"[gateway-sync] error during sync: {e!r}")


async def console_loop(bot: commands.Bot):
    loop = asyncio.get_event_loop()
    while True:
        try:
            line = await loop.run_in_executor(None, sys.stdin.readline)
        except Exception:
            break
        if not line:  # EOF stdin is /dev/null in systemd
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

        elif cmd == "force_score":
            if len(args) < 3:
                print("Usage: force_score <guild_id> <user_id> <score>")
                continue
            try:
                gid, uid, score = int(args[0]), int(args[1]), float(args[2])
                await bot.db.set_score(gid, uid, score)
                print(f"User {uid} in guild {gid} score set to {score}.")
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
            print("The web dashboard is now its own process - run web_service.py separately.")

        elif cmd == "help":
            print(HELP_TEXT)

        else:
            print(f"Unknown command: {cmd}. Type 'help' for a list.")


def _prefix(bot, message):
    if message.content[:4].lower() == "ccp ":
        return message.content[:4]
    return "ccp "


class SocialCreditBot(commands.AutoShardedBot):
    def __init__(self):
        super().__init__(
            command_prefix=_prefix,
            case_insensitive=True,
            intents=intents,
            tree_cls=CreditCommandTree,
            help_command=None,
            shard_count=SHARD_COUNT,
            shard_ids=SHARD_IDS,
            proxy=os.getenv("DISCORD_PROXY"),
            chunk_guilds_at_startup=False,
        )
        self.db = Database()
        self.ec_users: set[int] = set()
        self.start_time = None
        self._presence_index = 0
        self._synced_once = False

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
            from config.ranks import prestige_stars
            prestige_level = await self.db.get_counter(user.id, "prestige_level")
            star_suffix = f" {prestige_stars(prestige_level)}" if prestige_level > 0 else ""

            if user.id == OWNER_ID:
                return f"{str(user)}{OWNER_BADGE}{star_suffix}"
            if user.id in self.ec_users:
                return f"{str(user)} 【{_fullwidth('Winnie the Pooh')}】{star_suffix}"
            from config.shop import COSMETIC_META
            from config.achievements import ACHIEVEMENTS

            def _suffix_for(badge_id: str) -> str:
                if badge_id in COSMETIC_META:
                    return COSMETIC_META[badge_id]["suffix"]
                return badge_id

            badge_set = set(await self.db.get_cosmetic_badges(user.id))
            if not badge_set:
                return f"{str(user)}{star_suffix}"

            preferred = await self.db.get_badge_preference(user.id)
            if preferred and preferred in badge_set:
                return f"{str(user)} {_suffix_for(preferred)}{star_suffix}"

            _ORDER = ["voter", "verified", "figure", "influencer", "associate", "asset"]
            for badge_id in _ORDER:
                if badge_id in badge_set:
                    return f"{str(user)} {_suffix_for(badge_id)}{star_suffix}"

            for data in ACHIEVEMENTS.values():
                badge_id = data.get("badge")
                if badge_id and badge_id in badge_set:
                    return f"{str(user)} {_suffix_for(badge_id)}{star_suffix}"
            return f"{str(user)}{star_suffix}"
        return str(user)

    async def on_app_command_completion(
        self,
        interaction: discord.Interaction,
        command: discord.app_commands.Command | discord.app_commands.ContextMenu,
    ) -> None:
        t0, _ = _cmd_timing.pop(interaction.id, (time.time(), None))
        elapsed_ms = int((time.time() - t0) * 1000)
        qualified_name = command.qualified_name
        if interaction.guild_id and qualified_name:
            parts = qualified_name.split(' ', 1)
            asyncio.create_task(
                self.db.log_command(
                    interaction.guild_id, interaction.user.id,
                    parts[0], parts[1] if len(parts) > 1 else None,
                    elapsed_ms, True, None,
                )
            )

    _COOLDOWN_EXEMPT_COMMANDS = {"roll", "rollwaifu", "rollhusbando", "r", "rw", "rh"}

    async def process_commands(self, message: discord.Message) -> None:
        _current_user_id.set(message.author.id)
        ctx = await self.get_context(message)
        is_exempt = ctx.command and (
            ctx.command.qualified_name in self._COOLDOWN_EXEMPT_COMMANDS
            or ctx.invoked_with in self._COOLDOWN_EXEMPT_COMMANDS
        )
        if ctx.command and not is_exempt and not await _check_cmd_cooldown(message.author.id):
            r = get_redis()
            warned = await r.set(f"cmdwarn:{message.author.id}", "1", nx=True, ex=int(CMD_COOLDOWN) or 1)
            if warned:
                try:
                    await message.channel.send("Slow down, citizen.")
                except discord.Forbidden:
                    pass
            return
        if ctx.command and ctx.command.qualified_name not in OPTOUT_ALLOWED_PREFIX_COMMANDS:
            if await self.db.is_opted_out(message.author.id):
                try:
                    await message.channel.send(OPTOUT_BLOCKED_MESSAGE)
                except discord.Forbidden:
                    pass
                return
        if ctx.command and message.guild:
            await _log_command_usage(message.guild.id, message.author.id, ctx.command.qualified_name)
            _cmd_timing[message.id] = (time.time(), None)
        await self.invoke(ctx)
        if ctx.command and message.guild and message.id in _cmd_timing:
            t0, error_code = _cmd_timing.pop(message.id)
            if error_code is None:
                elapsed_ms = int((time.time() - t0) * 1000)
                parts = ctx.command.qualified_name.split(' ', 1)
                asyncio.create_task(
                    self.db.log_command(
                        message.guild.id, message.author.id,
                        parts[0], parts[1] if len(parts) > 1 else None,
                        elapsed_ms, True, None,
                    )
                )

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
        await self.load_extension("cogs.achievements")
        await self.load_extension("cogs.badges")
        await self.load_extension("cogs.privacy")
        await self.load_extension("cogs.prestige")
        await self.load_extension("cogs.serverrank")
        await self.load_extension("cogs.gacha")
        if IS_SCHEDULER:
            asyncio.create_task(_decay_task(self))
            asyncio.create_task(_rotate_presence_task(self))
        asyncio.create_task(_guild_notify_listener(self))
        if not IS_SCHEDULER:
            asyncio.create_task(_gateway_sync_listener(self))
        self.loop.create_task(console_loop(self))

    async def on_ready(self):
        if self.start_time is None:
            self.start_time = datetime.now(timezone.utc)
        small_guilds = [g for g in self.guilds if (g.member_count or 0) <= 5000 and not g.chunked]
        if small_guilds:
            await asyncio.gather(*[g.chunk() for g in small_guilds], return_exceptions=True)
        rank_names = {r["name"] for r in RANKS}
        exec_role_name = "Execution Date: Tomorrow"
        opted_out = await self.db.get_all_optouts()
        for guild in self.guilds:
            member_ids = [m.id for m in guild.members if not m.bot and m.id not in opted_out]
            await self.db.register_guild_members(guild.id, member_ids)
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
        if not self._synced_once:
            _global_cmds = self.tree.get_commands(guild=None)
            self.tree.clear_commands(guild=None)
            await self.tree.sync()
            for cmd in _global_cmds:
                self.tree.add_command(cmd)
            self._synced_once = True
            for guild in self.guilds:
                await self.db.set_guild_name(guild.id, guild.name)

        await self.change_presence(activity=_PRESENCE_CYCLE[self._presence_index])
        print(f"Online: {self.user}  |  Guilds: {len(self.guilds)}  |  Slash commands synced: {self._synced_once}")
        print("Type 'help' for console commands.")

    async def on_guild_join(self, guild: discord.Guild):
        member_ids = [m.id for m in guild.members if not m.bot]
        await self.db.register_guild_members(guild.id, member_ids)
        await self.db.log_guild_join(guild.id)
        await self.db.set_guild_name(guild.id, guild.name)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"Joined {guild.name} · registered {len(member_ids)} members · slash commands synced.")
        channel = guild.system_channel
        if channel is None:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    channel = ch
                    break
        if channel is not None:
            try:
                await channel.send(
                    "The Bureau has been added. Run `/guide` to get started.\n"
                    "Use `/serverrank visibility on` to display your server on the [global leaderboard](https://off-by-one.digital/social-credit/leaderboards).\n"
                    "Privacy policy: https://off-by-one.digital/social-credit/privacy"
                )
            except discord.Forbidden:
                pass

    async def on_guild_remove(self, guild: discord.Guild):
        try:
            member_count = getattr(guild, "member_count", None)
            now = int(time.time())
            ctx = await self.db.get_guild_departure_context(guild.id)
            joined_at = ctx["joined_at"]
            citizens = ctx["citizens"]
            score_events = ctx["score_events"]
            tenure_seconds = (now - joined_at) if joined_at else None
            engaged = citizens > 0 or score_events > 0
            if not engaged and tenure_seconds is not None and tenure_seconds < 3600:
                category = "Instant Kick"
                color = 0xE85454
                explanation = "Left within an hour with zero engagement · likely an immediate kick or rejection."
            elif not engaged:
                category = "Never Engaged"
                color = 0xF5A855
                explanation = "No messages or score activity were ever recorded here before it left."
            else:
                category = "Engaged Churn"
                color = 0x3DAA6E
                explanation = "Had real activity before leaving · an actual community churned, not a rejection."

            await self.db.log_guild_leave(
                guild.id, member_count, tenure_seconds, citizens, score_events, category,
            )

            r = get_redis()
            cmd_key = f"cmdlog:{guild.id}"
            raw_entries = await r.lrange(cmd_key, 0, CMD_LOG_MAX - 1)
            await r.delete(cmd_key)
            if raw_entries:
                lines = []
                for raw in raw_entries:
                    entry = json.loads(raw)
                    lines.append(f"`{entry['command']}` · <@{entry['user_id']}> · <t:{entry['ts']}:R>")
                last_commands = "\n".join(lines)
            else:
                last_commands = "No commands logged before this guild left."

            embed = discord.Embed(
                title="中华人民共和国社会信用局 · GUILD DEPARTURE",
                color=color,
            )
            embed.add_field(name="Guild", value=f"{guild.name}\n`{guild.id}`", inline=False)
            embed.add_field(
                name="Joined",
                value=f"<t:{joined_at}:R> (<t:{joined_at}:f>)" if joined_at else "No join record",
                inline=False,
            )
            embed.add_field(name="Members", value=str(member_count) if member_count is not None else "?", inline=True)
            embed.add_field(name="Citizens", value=str(citizens), inline=True)
            embed.add_field(name="Score Events", value=str(score_events), inline=True)
            embed.add_field(name="Category", value=f"**{category}**\n{explanation}", inline=False)
            embed.add_field(name="Last Commands Used", value=last_commands, inline=False)

            try:
                owner = await self.fetch_user(OWNER_ID)
                await owner.send(embed=embed)
            except (discord.Forbidden, discord.HTTPException):
                pass
        except Exception as e:
            print(f"on_guild_remove failed for {getattr(guild, 'id', '?')}: {e}")

    async def on_guild_update(self, before: discord.Guild, after: discord.Guild):
        if before.name != after.name:
            await self.db.set_guild_name(after.id, after.name)

    async def on_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        cause = getattr(error, "__cause__", error)
        if ctx.command and ctx.guild and ctx.message.id in _cmd_timing:
            t0, _ = _cmd_timing.pop(ctx.message.id)
            elapsed_ms = int((time.time() - t0) * 1000)
            parts = ctx.command.qualified_name.split(' ', 1)
            asyncio.create_task(
                self.db.log_command(
                    ctx.guild.id, ctx.author.id,
                    parts[0], parts[1] if len(parts) > 1 else None,
                    elapsed_ms, False, type(cause).__name__,
                )
            )
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
        elif isinstance(error, commands.MissingRequiredArgument):
            await ctx.send(f"Missing argument: `{error.param.name}`. Use `ccp help` for usage.")
        elif isinstance(error, (commands.MemberNotFound, commands.UserNotFound)):
            await ctx.send(f"Member `{error.argument}` not found.")
        elif isinstance(error, (commands.ChannelNotFound, commands.RoleNotFound)):
            await ctx.send(f"Could not find `{error.argument}`. Try mentioning it directly.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"Invalid argument: {error}")
        elif isinstance(cause, discord.DiscordServerError):
            pass
        elif not isinstance(error, commands.CommandNotFound):
            raise error

    async def on_member_join(self, member: discord.Member):
        if not member.bot and not await self.db.is_opted_out(member.id):
            await self.db.register_user(member.guild.id, member.id)
        await cache_delete(f"memberleft:{member.guild.id}:{member.id}")

    async def on_member_remove(self, member: discord.Member):
        if not member.bot:
            await cache_set(f"memberleft:{member.guild.id}:{member.id}", "1", ex=86400 * 90)


if __name__ == "__main__":
    bot = SocialCreditBot()
    bot.run(os.getenv("DISCORD_TOKEN"))
