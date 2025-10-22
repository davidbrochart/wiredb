from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from anyio import AsyncContextManagerMixin, Lock, create_task_group, get_cancelled_exc_class, sleep_forever
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from pycrdt import Doc, Channel

from wiredb import Provider, ClientWire as _ClientWire

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: nocover
    from typing_extensions import Self


class ClientWire(AsyncContextManagerMixin, _ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, *, host: str, port: int) -> None:
        super().__init__(doc)
        self._id = id
        self._host = host
        self._port = port

    async def _connect_ws(self) -> None:
        try:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"{self._host}:{self._port}/{self._id}",
                keepalive_ping_interval_seconds=None,
            ) as ws:
                channel = HttpxWebsocket(ws, self._id)
                async with Provider(self._doc, channel):
                    await sleep_forever()
        except get_cancelled_exc_class():
            pass

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as self._task_group:
            self._task_group.start_soon(self._connect_ws)
            yield self
            self._task_group.cancel_scope.cancel()


class HttpxWebsocket(Channel):
    def __init__(self, websocket: AsyncWebSocketSession, path: str) -> None:
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    async def __anext__(self) -> bytes:
        try:
            message = await self.recv()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def path(self) -> str:
        return self._path  # pragma: nocover

    async def send(self, message: bytes):
        async with self._send_lock:
            await self._websocket.send_bytes(message)

    async def recv(self) -> bytes:
        b = await self._websocket.receive_bytes()
        return bytes(b)
