import json

from infra.redis_client import get_redis

GUILD_NOTIFY_CHANNEL = "guild-notify"


async def publish_guild_notify(guild_id: int, event_type: str, data: dict | None = None) -> None:
    r = get_redis()
    payload = json.dumps({"guild_id": guild_id, "event_type": event_type, "data": data or {}})
    await r.publish(GUILD_NOTIFY_CHANNEL, payload)
