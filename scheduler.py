import os
import asyncio
from discord.ext import commands
from bot import intents, _decay_task, _rotate_presence_task, _guild_notify_listener, console_loop
from database.db import Database
from infra.run_mode import SHARD_COUNT


class SchedulerBot(commands.Bot):
    """Singleton background-job process.

    Owns everything that must run exactly once across the whole deployment:
    score decay, presence rotation, the web dashboard, and the propaganda
    close/conclude, daily poster broadcast, and top.gg vote-reminder/stats
    loops. Loads only scheduler-only cogs with zero app_commands/prefix
    commands/listeners, so it never risks double-handling a Discord
    interaction or message even if its gateway session overlaps with a
    gateway worker process for the same bot token.

    cogs.stocks is deliberately not split or loaded here -- its price tick
    loop shares in-memory state with the buy/sell/turbo command handlers on
    the gateway process, and splitting it before that state moves to Redis
    would leave gateway workers with no price data. See CLAUDE.md.
    """

    def __init__(self):
        super().__init__(
            command_prefix="ccp ",
            intents=intents,
            help_command=None,
            shard_id=0 if SHARD_COUNT else None,
            shard_count=SHARD_COUNT,
        )
        self.db = Database()
        self.ec_users: set[int] = set()
        self.start_time = None

    async def _tree_error(self, interaction, error):
        from discord.app_commands import CommandNotFound
        if isinstance(error, CommandNotFound):
            return

    async def setup_hook(self):
        self.tree.on_error = self._tree_error
        await self.db.init()
        self.ec_users = await self.db.get_all_eternal_chairmen()
        await self.load_extension("cogs.propaganda_scheduler")
        await self.load_extension("cogs.posters_scheduler")
        await self.load_extension("cogs.voting_scheduler")
        await self.load_extension("cogs.achievements_scheduler")
        await self.load_extension("cogs.admin_rpc_scheduler")
        asyncio.create_task(_decay_task(self))
        asyncio.create_task(_rotate_presence_task(self))
        asyncio.create_task(_guild_notify_listener(self))
        self.loop.create_task(console_loop(self))

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.CommandNotFound):
            return

    async def on_ready(self):
        if self.start_time is None:
            from datetime import datetime, timezone
            self.start_time = datetime.now(timezone.utc)
        print(f"[scheduler] Online: {self.user}  |  Guilds: {len(self.guilds)}")
        print("Type 'help' for console commands.")


if __name__ == "__main__":
    bot = SchedulerBot()
    bot.run(os.getenv("DISCORD_TOKEN"))
