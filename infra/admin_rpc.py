import asyncio
import json
import secrets

from infra.redis_client import get_redis

ADMIN_RPC_CHANNEL = "admin-rpc"
_RESPONSE_PREFIX = "admin-rpc-response:"


async def _listen_one(pubsub):
    async for message in pubsub.listen():
        if message.get("type") == "message":
            return json.loads(message["data"])


async def call_admin_rpc(action: str, payload: dict | None = None, timeout: float = 10.0) -> dict:
    r = get_redis()
    request_id = secrets.token_hex(16)
    response_channel = _RESPONSE_PREFIX + request_id
    pubsub = r.pubsub()
    await pubsub.subscribe(response_channel)
    try:
        await r.publish(ADMIN_RPC_CHANNEL, json.dumps({
            "request_id": request_id,
            "action": action,
            "payload": payload or {},
        }))
        try:
            return await asyncio.wait_for(_listen_one(pubsub), timeout)
        except asyncio.TimeoutError:
            return {"error": "Request timed out waiting for the bot process to respond."}
    finally:
        await pubsub.unsubscribe(response_channel)
        await pubsub.aclose()


async def fire_admin_rpc(action: str, payload: dict | None = None) -> None:
    r = get_redis()
    await r.publish(ADMIN_RPC_CHANNEL, json.dumps({
        "request_id": None,
        "action": action,
        "payload": payload or {},
    }))


async def publish_admin_rpc_response(request_id: str, result: dict) -> None:
    if not request_id:
        return
    r = get_redis()
    await r.publish(_RESPONSE_PREFIX + request_id, json.dumps(result))
