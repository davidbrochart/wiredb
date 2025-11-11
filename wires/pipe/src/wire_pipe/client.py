from __future__ import annotations

import os
from contextlib import AsyncExitStack
from types import TracebackType

from anyio import create_task_group
from pycrdt import Doc

from wiredb import AsyncClient, AsyncClientMixin

from .server import STOP, Pipe


class AsyncPipeClient(AsyncClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = True,
        auto_pull: bool = True,
        *,
        connection,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
        self._auto_pull = auto_pull
        self._sender, self._receiver, self._server_sender, self._server_receiver = (
            connection
        )

    async def __aenter__(self) -> "AsyncPipeClient":
        async with AsyncExitStack() as exit_stack:
            tg = await exit_stack.enter_async_context(create_task_group())
            channel = Pipe(tg, self._sender, self._receiver, self._id)
            self._client = await exit_stack.enter_async_context(
                AsyncClient(channel, self._doc, self._auto_push, self._auto_pull)
            )
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        os.write(self._sender, STOP)
        os.write(self._server_sender, STOP)
        os.close(self._sender)
        os.close(self._receiver)
        os.close(self._server_sender)
        os.close(self._server_receiver)
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)
