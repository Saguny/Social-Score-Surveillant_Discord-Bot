import asyncio
import json
import logging

from aiohttp import web

from infra.redis_client import get_redis

logger = logging.getLogger(__name__)

SSE_CHANNEL = "sse-events"


class SSEHub:
    def __init__(self):
        self._client_count = 0

    def client_count(self) -> int:
        return self._client_count

    async def publish(self, event: str, data) -> None:
        r = get_redis()
        await r.publish(SSE_CHANNEL, json.dumps({"event": event, "data": data}))

    async def stream(self, request) -> web.StreamResponse:
        response = web.StreamResponse(
            status=200,
            headers={
                "Content-Type": "text/event-stream",
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
        await response.prepare(request)
        r = get_redis()
        pubsub = r.pubsub()
        await pubsub.subscribe(SSE_CHANNEL)
        self._client_count += 1
        try:
            await response.write(b": connected\n\n")
            while True:
                message = await pubsub.get_message(timeout=20, ignore_subscribe_messages=True)
                if message is None:
                    await response.write(b": keepalive\n\n")
                    continue
                try:
                    payload = json.loads(message["data"])
                except (TypeError, ValueError):
                    continue
                line = f"event: {payload['event']}\ndata: {json.dumps(payload['data'])}\n\n".encode("utf-8")
                await response.write(line)
        except (ConnectionResetError, asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._client_count -= 1
            await pubsub.unsubscribe(SSE_CHANNEL)
            await pubsub.aclose()
        return response
