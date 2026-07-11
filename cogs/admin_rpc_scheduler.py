import asyncio
import json
import time

import discord
from discord.ext import commands

from infra.redis_client import get_redis
from infra.admin_rpc import ADMIN_RPC_CHANNEL, publish_admin_rpc_response


def _find_writable_channel(guild: discord.Guild) -> discord.TextChannel | None:
    candidates = []
    if guild.system_channel:
        candidates.append(guild.system_channel)
    candidates.extend(c for c in guild.text_channels if c != guild.system_channel)
    for channel in candidates:
        everyone_perms = channel.permissions_for(guild.default_role)
        bot_perms = channel.permissions_for(guild.me)
        if (
            everyone_perms.view_channel and everyone_perms.send_messages
            and bot_perms.view_channel and bot_perms.send_messages and bot_perms.embed_links
        ):
            return channel
    return None


class AdminRpcScheduler(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.db = bot.db

    async def cog_load(self):
        self._task = asyncio.create_task(self._listen())

    async def cog_unload(self):
        self._task.cancel()

    async def _listen(self):
        await self.bot.wait_until_ready()
        r = get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(ADMIN_RPC_CHANNEL)
        async for message in pubsub.listen():
            if message.get("type") != "message":
                continue
            try:
                payload = json.loads(message["data"])
            except (TypeError, ValueError):
                continue
            asyncio.create_task(self._handle(payload))

    async def _handle(self, payload: dict):
        request_id = payload.get("request_id")
        action = payload.get("action", "")
        args = payload.get("payload", {}) or {}
        try:
            result = await self._dispatch(action, args)
        except Exception as e:
            print(f"[admin_rpc] error handling action={action!r}: {e!r}")
            result = {"error": str(e)}
        await publish_admin_rpc_response(request_id, result)

    async def _dispatch(self, action: str, args: dict) -> dict:
        bot = self.bot
        db = self.db

        if action == "sync":
            r = get_redis()
            await r.publish("gateway-sync", "{}")
            return {"output": "Sync request dispatched to all gateway workers."}

        if action == "guilds":
            lines = [f"{g.id}  {g.name}  ({g.member_count} members)" for g in bot.guilds]
            return {"output": "\n".join(lines) or "No guilds."}

        if action == "reload":
            cog = args.get("cog", "")
            if not cog:
                return {"error": "Usage: reload <cog>"}
            await bot.reload_extension(cog)
            return {"output": f"{cog} reloaded."}

        if action == "restart":
            asyncio.create_task(self._delayed_restart())
            return {"output": "Restarting scheduler..."}

        if action == "shutdown":
            asyncio.create_task(self._delayed_shutdown())
            return {"output": "Shutting down scheduler..."}

        if action == "get_status":
            uptime = int(time.time() - bot.start_time.timestamp()) if getattr(bot, "start_time", None) else 0
            scoring_cog = bot.get_cog("Scoring")
            executor = getattr(scoring_cog, "_executor", None)
            max_workers = getattr(executor, "_max_workers", None) if executor else None
            active_workers = len(getattr(executor, "_processes", None) or {}) if executor else None
            if max_workers is None:
                from infra.redis_cache import cache_get
                cached = await cache_get("gateway:sentiment_workers")
                if cached:
                    max_workers = int(cached)
                    active_workers = max_workers
            return {
                "total_guilds": len(bot.guilds),
                "uptime_seconds": uptime,
                "discord_ping_ms": round(bot.latency * 1000, 1) if bot.latency else None,
                "sentiment_workers_max": max_workers if isinstance(max_workers, int) else None,
                "sentiment_workers_active": active_workers if isinstance(active_workers, int) else None,
            }

        if action == "get_guild_list":
            guilds = sorted(bot.guilds, key=lambda g: g.name.lower())
            return {
                "guilds": [
                    {"id": str(g.id), "name": g.name, "member_count": g.member_count or 0}
                    for g in guilds
                ]
            }

        if action == "user_lookup":
            return await self._user_lookup(args)

        if action == "user_yuan_adjust":
            return await self._user_yuan_adjust(args)

        if action == "broadcast_embed":
            return await self._broadcast_embed(args)

        if action == "process_vote":
            from cogs.voting import process_vote
            user_id = args.get("user_id")
            if user_id is not None:
                await process_vote(bot, int(user_id))
            return {"output": "ok"}

        if action == "dm_user":
            user_id = args.get("user_id")
            message = str(args.get("message", ""))[:2000]
            if user_id and message:
                try:
                    user = await bot.fetch_user(int(user_id))
                    await user.send(message)
                except Exception:
                    pass
            return {"output": "ok"}

        if action == "check_contribution_milestone":
            user_id       = args.get("user_id")
            contributions = args.get("contributions", 0)
            if user_id:
                from cogs.achievements import check_milestone, unlock
                uid = int(user_id)
                for guild in bot.guilds:
                    member = guild.get_member(uid)
                    if member:
                        await check_milestone(
                            bot, guild, member,
                            "gacha_contributions", contributions,
                        )
                        break
            return {"output": "ok"}

        return {"error": f"Unknown action: {action}"}

    async def _delayed_restart(self):
        await asyncio.sleep(0.5)
        await self.bot.close()
        import os
        os._exit(42)

    async def _delayed_shutdown(self):
        await asyncio.sleep(0.5)
        await self.bot.close()

    async def _user_lookup(self, args: dict) -> dict:
        bot = self.bot
        try:
            user_id = int(args.get("user_id"))
        except (TypeError, ValueError):
            return {"error": "Invalid user ID."}

        discord_user = bot.get_user(user_id)
        if not discord_user:
            try:
                discord_user = await bot.fetch_user(user_id)
            except discord.NotFound:
                return {"error": f"No Discord user found with ID {user_id}."}
            except discord.HTTPException as e:
                return {"error": str(e)}

        guilds = []
        for guild in bot.guilds:
            member = guild.get_member(user_id)
            if not member:
                continue
            row = await self.db.get_user(guild.id, user_id)
            guilds.append({
                "guild_id": str(guild.id),
                "guild_name": guild.name,
                "yuan": row["yuan"],
                "score": row["score"],
            })

        return {
            "user_id": str(discord_user.id),
            "username": str(discord_user),
            "avatar_url": discord_user.display_avatar.url,
            "guilds": guilds,
        }

    async def _user_yuan_adjust(self, args: dict) -> dict:
        bot = self.bot
        try:
            guild_id = int(args.get("guild_id"))
            user_id = int(args.get("user_id"))
            amount = int(args.get("amount"))
        except (TypeError, ValueError):
            return {"error": "guild_id, user_id, and amount must be integers."}

        if amount == 0:
            return {"error": "Amount must be non-zero."}

        guild = bot.get_guild(guild_id)
        if not guild:
            return {"error": f"Bot is not in guild {guild_id}."}

        await self.db.adjust_yuan(guild_id, user_id, amount)
        row = await self.db.get_user(guild_id, user_id)
        return {"yuan": row["yuan"]}

    async def _broadcast_embed(self, args: dict) -> dict:
        bot = self.bot
        target = str(args.get("target", "all")).strip()
        title = (args.get("title") or "").strip()
        description = (args.get("description") or "").strip()
        color_raw = (args.get("color") or "").strip().lstrip("#")
        image_url = (args.get("image_url") or "").strip()
        thumbnail_url = (args.get("thumbnail_url") or "").strip()
        fields = args.get("fields") or []
        button_label = (args.get("button_label") or "").strip()
        button_url = (args.get("button_url") or "").strip()

        if not title and not description:
            return {"error": "Embed needs a title or description."}

        try:
            color = int(color_raw, 16) if color_raw else 0xCC0000
        except ValueError:
            return {"error": "Invalid color hex."}

        view = None
        if button_label and button_url:
            if not (button_url.startswith("http://") or button_url.startswith("https://")):
                return {"error": "Button URL must start with http:// or https://"}
            view = discord.ui.View()
            view.add_item(discord.ui.Button(label=button_label[:80], url=button_url, style=discord.ButtonStyle.link))

        def build_embed():
            embed = discord.Embed(title=title or None, description=description or None, color=color)
            if image_url:
                embed.set_image(url=image_url)
            if thumbnail_url:
                embed.set_thumbnail(url=thumbnail_url)
            for f in fields[:25]:
                name = (f.get("name") or "").strip()
                value = (f.get("value") or "").strip()
                if not name or not value:
                    continue
                embed.add_field(name=name, value=value, inline=bool(f.get("inline")))
            return embed

        if target == "all":
            guilds = list(bot.guilds)
        else:
            try:
                gid = int(target)
            except ValueError:
                return {"error": "Invalid guild id."}
            guild = bot.get_guild(gid)
            if not guild:
                return {"error": f"Bot is not in guild {gid}."}
            guilds = [guild]

        if not guilds:
            return {"error": "No target guilds."}

        results = []
        for guild in guilds:
            embed = build_embed()
            channel = _find_writable_channel(guild)
            if not channel:
                results.append({
                    "guild_id": str(guild.id), "guild_name": guild.name,
                    "status": "skipped", "detail": "No channel writable by @everyone found.",
                })
                continue
            try:
                if view is not None:
                    await channel.send(embed=embed, view=view)
                else:
                    await channel.send(embed=embed)
                results.append({
                    "guild_id": str(guild.id), "guild_name": guild.name,
                    "status": "sent", "detail": f"#{channel.name}",
                })
            except Exception as e:
                results.append({
                    "guild_id": str(guild.id), "guild_name": guild.name,
                    "status": "error", "detail": str(e),
                })

        sent = sum(1 for r in results if r["status"] == "sent")
        return {"results": results, "sent": sent, "total": len(results)}


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminRpcScheduler(bot))
