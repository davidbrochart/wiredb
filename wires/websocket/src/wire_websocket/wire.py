from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType

from httpx_ws import aconnect_ws
from pycrdt import Doc, Provider
from pycrdt.websocket.websocket import HttpxWebsocket


class Wire:
    def __init__(self, doc: Doc, id: str, *, host: str, port: int) -> None:
        self._doc = doc
        self._id = id
        self._host = host
        self._port = port

    async def __aenter__(self) -> Self:
        async with AsyncExitStack() as exit_stack:
            ws = await exit_stack.enter_async_context(aconnect_ws(f"{self._host}:{self._port}/{self._id}"))
            channel = HttpxWebsocket(ws, self._id)
            await exit_stack.enter_async_context(Provider(self._doc, channel))
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
