from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType

from pycrdt import Doc

from wiredb import AsyncClient, AsyncClientMixin

from .server import AsyncMemoryServer, Memory


class AsyncMemoryClient(AsyncClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = True,
        auto_pull: bool = True,
        *,
        server: AsyncMemoryServer,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
        self._auto_pull = auto_pull
        self._server = server

    async def __aenter__(self) -> AsyncMemoryClient:
        async with AsyncExitStack() as exit_stack:
            _send_stream, _receive_stream = await self._server.connect(self._id)
            send_stream = await exit_stack.enter_async_context(_send_stream)
            receive_stream = await exit_stack.enter_async_context(_receive_stream)
            self.channel = Memory(send_stream, receive_stream, self._id)
            self._client = await exit_stack.enter_async_context(
                AsyncClient(self.channel, self._doc, self._auto_push, self._auto_pull)
            )
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
