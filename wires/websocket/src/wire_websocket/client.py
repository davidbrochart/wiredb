from __future__ import annotations

import sys
from collections.abc import Generator
from contextlib import AsyncExitStack, ExitStack, contextmanager
from queue import Empty
from types import TracebackType

from anyio import (
    TASK_STATUS_IGNORED,
    Lock,
    create_task_group,
    get_cancelled_exc_class,
    sleep_forever,
)
from anyio.abc import TaskStatus
from httpx import Cookies
from httpx_ws import AsyncWebSocketSession, WebSocketSession, aconnect_ws, connect_ws
from pycrdt import Doc

from wiredb import (
    AsyncChannel,
    AsyncClient,
    AsyncClientMixin,
    Channel,
    Client,
    ClientMixin,
)

if sys.version_info >= (3, 11):
    pass
else:  # pragma: nocover
    pass


class WebSocketClient(ClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = False,
        *,
        host: str,
        port: int,
        cookies: Cookies | None = None,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
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
            self._channel = HttpxWebSocket(ws, self._id)
            yield

    def __enter__(self) -> "WebSocketClient":
        with ExitStack() as exit_stack:
            exit_stack.enter_context(self._connect_ws())
            self._client = exit_stack.enter_context(
                Client(self._channel, self._doc, self._auto_push)
            )
            self._exit_stack = exit_stack.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return self._exit_stack.__exit__(exc_type, exc_val, exc_tb)


class AsyncWebSocketClient(AsyncClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = True,
        auto_pull: bool = True,
        *,
        host: str,
        port: int,
        cookies: Cookies | None = None,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
        self._auto_pull = auto_pull
        self._host = host
        self._port = port
        self._cookies = cookies

    async def _aconnect_ws(
        self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED
    ) -> None:
        try:
            ws: AsyncWebSocketSession
            async with aconnect_ws(
                f"{self._host}:{self._port}/{self._id}",
                keepalive_ping_interval_seconds=None,
                cookies=self._cookies,
            ) as ws:
                self._channel = HttpxAsyncWebSocket(ws, self._id)
                task_status.started()
                await sleep_forever()
        except get_cancelled_exc_class():
            pass

    async def __aenter__(self) -> AsyncWebSocketClient:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            await self._task_group.start(self._aconnect_ws)
            self._client = await exit_stack.enter_async_context(
                AsyncClient(self._channel, self._doc, self._auto_push, self._auto_pull)
            )
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._task_group.cancel_scope.cancel()
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)


class HttpxWebSocket(Channel):
    def __init__(self, websocket: WebSocketSession, path: str) -> None:
        self._websocket = websocket
        self._path = path

    @property
    def id(self) -> str:
        return self._path  # pragma: nocover

    def send(self, message: bytes) -> None:
        self._websocket.send_bytes(message)

    def receive(self, timeout: float | None = None) -> bytes:
        try:
            return bytes(self._websocket.receive_bytes(timeout))
        except Empty:
            raise TimeoutError()


class HttpxAsyncWebSocket(AsyncChannel):
    def __init__(self, websocket: AsyncWebSocketSession, path: str) -> None:
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    async def __anext__(self) -> bytes:
        try:
            message = await self.receive()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def id(self) -> str:
        return self._path  # pragma: nocover

    async def send(self, message: bytes) -> None:
        async with self._send_lock:
            await self._websocket.send_bytes(message)

    async def receive(self) -> bytes:
        return bytes(await self._websocket.receive_bytes())
