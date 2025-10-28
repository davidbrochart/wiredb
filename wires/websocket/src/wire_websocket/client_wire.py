from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import AsyncExitStack, ExitStack, contextmanager
from types import TracebackType
from typing import cast

from anyio import Lock, TASK_STATUS_IGNORED, create_task_group, get_cancelled_exc_class, sleep_forever
from anyio.abc import TaskStatus
from httpx import Cookies
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from httpx_ws import WebSocketSession, connect_ws
from pycrdt import Doc

from wiredb import Channel, ClientWire as _ClientWire

if sys.version_info >= (3, 11):
    pass
else:  # pragma: nocover
    pass


class ClientWire(_ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, auto_update: bool = True, *, host: str, port: int, cookies: Cookies | None = None) -> None:
        super().__init__(doc, auto_update)
        self._id = id
        self._host = host
        self._port = port
        self._cookies = cookies

    @contextmanager
    def _connect_ws(self) -> Generator[None]:
        ws: WebSocketSession
        with connect_ws(
            f"{self._host}:{self._port}/{self._id}",
            keepalive_ping_interval_seconds=None,
            cookies=self._cookies,
        ) as ws:
            self.channel = HttpxWebsocket(ws, self._id)
            yield

    async def _aconnect_ws(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        try:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"{self._host}:{self._port}/{self._id}",
                keepalive_ping_interval_seconds=None,
                cookies=self._cookies,
            ) as ws:
                self.channel = HttpxWebsocket(ws, self._id)
                task_status.started()
                await sleep_forever()
        except get_cancelled_exc_class():
            pass

    def __enter__(self) -> ClientWire:
        with ExitStack() as exit_stack:
            exit_stack.enter_context(self._connect_ws())
            super().__enter__()
            exit_stack.push(super().__exit__)
            self._exit_stack0 = exit_stack.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return self._exit_stack0.__exit__(exc_type, exc_val, exc_tb)

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            self._task_group0 = await exit_stack.enter_async_context(create_task_group())
            await self._task_group0.start(self._aconnect_ws)
            await super().__aenter__()
            exit_stack.push_async_exit(super().__aexit__)
            self._exit_stack1 = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._task_group0.cancel_scope.cancel()
        return await self._exit_stack1.__aexit__(exc_type, exc_val, exc_tb)


class HttpxWebsocket(Channel):
    def __init__(self, websocket: AsyncWebSocketSession | WebSocketSession, path: str) -> None:
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    def __next__(self) -> bytes:  # pragma: nocover
        try:
            message = self.recv()
        except Exception:
            raise StopAsyncIteration()

        return message

    async def __anext__(self) -> bytes:
        try:
            message = await self.arecv()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def path(self) -> str:
        return self._path  # pragma: nocover

    def send(self, message: bytes):
        websocket = cast(WebSocketSession, self._websocket)
        websocket.send_bytes(message)

    def recv(self) -> bytes:
        websocket = cast(WebSocketSession, self._websocket)
        b = websocket.receive_bytes(0)
        return bytes(b)

    async def asend(self, message: bytes):
        websocket = cast(AsyncWebSocketSession, self._websocket)
        async with self._send_lock:
            await websocket.send_bytes(message)

    async def arecv(self) -> bytes:
        websocket = cast(AsyncWebSocketSession, self._websocket)
        b = await websocket.receive_bytes()
        return bytes(b)
