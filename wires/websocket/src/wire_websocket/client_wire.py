from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Generator
from contextlib import asynccontextmanager, contextmanager

from anyio import AsyncContextManagerMixin, ContextManagerMixin, Lock, TASK_STATUS_IGNORED, create_task_group, get_cancelled_exc_class, sleep_forever
from anyio.abc import TaskStatus
from httpx import Cookies
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from httpx_ws import AsyncWebSocketSession, WebSocketSession, aconnect_ws, connect_ws
from pycrdt import Doc, Channel

from wiredb import Provider, ClientWire as _ClientWire

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: nocover
    from typing_extensions import Self


class ClientWire(AsyncContextManagerMixin, ContextManagerMixin, _ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, auto_update: bool = True, *, host: str, port: int, cookies: Cookies | None = None) -> None:
        super().__init__(doc, auto_update)
        self._id = id
        self._host = host
        self._port = port
        self._cookies = cookies

    def _connect_ws(self) -> None:
        ws = connect_ws(
            f"{self._host}:{self._port}/{self._id}",
            keepalive_ping_interval_seconds=None,
        )
        channel = HttpxWebsocket(ws, self._id)
        async with Provider(self._doc, channel):
            await sleep_forever()

    async def _aconnect_ws(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        try:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"{self._host}:{self._port}/{self._id}",
                keepalive_ping_interval_seconds=None,
                cookies=self._cookies,
            ) as ws:
                self.channel = HttpxWebsocket(ws, self._id)
                async with Provider(self):
                    task_status.started()
                    await sleep_forever()
        except get_cancelled_exc_class():
            pass

    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        with
            self._connect_ws()
            yield self

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as self._task_group:
            await self._task_group.start(self._aconnect_ws)
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
