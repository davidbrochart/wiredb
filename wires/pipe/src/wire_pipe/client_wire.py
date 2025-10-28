from __future__ import annotations

import os
from contextlib import AsyncExitStack
from types import TracebackType

from anyio import create_task_group
from pycrdt import Doc
from wiredb import ClientWire as _ClientWire

from .server_wire import STOP, Pipe


class ClientWire(_ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, auto_update: bool = True, *, connection) -> None:
        super().__init__(doc, auto_update)
        self._id = id
        self._sender, self._receiver, self._self_sender = connection

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            tg = await exit_stack.enter_async_context(create_task_group())
            self.channel = Pipe(tg, self._sender, self._receiver, self._id)
            await super().__aenter__()
            exit_stack.push_async_exit(super().__aexit__)
            self._exit_stack0 = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        try:
            os.fdopen(self._self_sender, "wb", buffering=0).write(STOP)
        except BaseException:  # pragma: nocover
            pass
        return await self._exit_stack0.__aexit__(exc_type, exc_val, exc_tb)
