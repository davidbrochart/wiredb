from __future__ import annotations

from collections.abc import Awaitable
from typing import Any, Callable

from wiredb import AsyncChannel


class ASGIWebsocket(AsyncChannel):
    def __init__(
        self,
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
        path: str,
    ) -> None:
        self._receive = receive
        self._send = send
        self._path = path

    @property
    def id(self) -> str:
        return self._path

    async def __anext__(self) -> bytes:
        return await self.receive()

    async def send(self, message: bytes) -> None:
        await self._send(
            dict(
                type="websocket.send",
                bytes=message,
            )
        )

    async def receive(self) -> bytes:
        message = await self._receive()
        if message["type"] == "websocket.receive":
            return message["bytes"]
        if message["type"] == "websocket.disconnect":
            raise StopAsyncIteration()
        return b""  # pragma: nocover


class ASGIServer:
    def __init__(
        self,
        serve: Callable[[ASGIWebsocket], Awaitable[None]],
    ) -> None:
        self._serve = serve

    async def __call__(
        self,
        scope: dict[str, Any],
        receive: Callable[[], Awaitable[dict[str, Any]]],
        send: Callable[[dict[str, Any]], Awaitable[None]],
    ):
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    await send({"type": "lifespan.startup.complete"})
                elif message["type"] == "lifespan.shutdown":
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        elif scope["type"] == "websocket":
            msg = await receive()
            if msg["type"] == "websocket.connect":
                await send({"type": "websocket.accept"})
                websocket = ASGIWebsocket(receive, send, scope["path"])
                await self._serve(websocket)
