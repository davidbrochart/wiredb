from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType

from anyio import Lock
from httpx_ws import AsyncWebSocketSession, aconnect_ws
from pycrdt import Channel

from wiredb import Provider, ClientWire as _ClientWire


class ClientWire(_ClientWire):
    def __init__(self, id: str, *, host: str, port: int) -> None:
        super().__init__()
        self._id = id
        self._host = host
        self._port = port

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            ws: AsyncWebSocketSession = await exit_stack.enter_async_context(
                aconnect_ws(
                    f"{self._host}:{self._port}/{self._id}",
                    keepalive_ping_interval_seconds=None,
                )
            )
            channel = HttpxWebsocket(ws, self._id)
            await exit_stack.enter_async_context(Provider(self._doc, channel))
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)


class HttpxWebsocket(Channel):
    def __init__(self, websocket: AsyncWebSocketSession, path: str) -> None:
        self._websocket = websocket
        self._path = path
        self._send_lock = Lock()

    async def __anext__(self) -> bytes:
        try:
            message = await self.recv()
        except Exception:
            raise StopAsyncIteration()

        return message

    @property
    def path(self) -> str:
        return self._path

    async def send(self, message: bytes):
        async with self._send_lock:
            await self._websocket.send_bytes(message)

    async def recv(self) -> bytes:
        b = await self._websocket.receive_bytes()
        return bytes(b)
