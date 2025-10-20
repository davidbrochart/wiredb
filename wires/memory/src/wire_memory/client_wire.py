from __future__ import annotations

from contextlib import AsyncExitStack
from types import TracebackType

from pycrdt import Doc
from wiredb import Provider, ClientWire as _ClientWire

from .server_wire import Memory, ServerWire


class ClientWire(_ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, *, server: ServerWire) -> None:
        super().__init__(doc)
        self._id = id
        self._server = server

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            _send_stream, _receive_stream = await self._server.connect(self._id)
            send_stream = await exit_stack.enter_async_context(_send_stream)
            receive_stream = await exit_stack.enter_async_context(_receive_stream)
            channel = Memory(send_stream, receive_stream, self._id)
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
