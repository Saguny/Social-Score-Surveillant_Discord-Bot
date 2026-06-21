import asyncio
import json
import logging

from aiohttp import web

logger = logging.getLogger(__name__)


class SSEHub:
    def __init__(self):
        self._clients: set[asyncio.Queue] = set()

    def client_count(self) -> int:
        return len(self._clients)

    async def publish(self, event: str, data) -> None:
        if not self._clients:
            return
        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n".encode("utf-8")
        dead = []
        for queue in list(self._clients):
            try:
                queue.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(queue)
        for queue in dead:
            self._clients.discard(queue)

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
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._clients.add(queue)
        try:
            await response.write(b": connected\n\n")
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=20)
                    await response.write(payload)
                except asyncio.TimeoutError:
                    await response.write(b": keepalive\n\n")
        except (ConnectionResetError, asyncio.CancelledError, ConnectionError):
            pass
        finally:
            self._clients.discard(queue)
        return response
