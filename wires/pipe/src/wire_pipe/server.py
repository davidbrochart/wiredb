from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AsyncExitStack
from functools import partial
from types import TracebackType

from anyio import (
    Lock,
    create_memory_object_stream,
    create_task_group,
    from_thread,
    to_thread,
)
from anyio.abc import TaskGroup
from anyio.streams.buffered import BufferedByteReceiveStream

from wiredb import AsyncChannel, AsyncServer, Room

SEPARATOR = bytes([226, 164, 131, 121, 240, 77, 100, 52])
STOP = bytes([80, 131, 218, 244, 198, 47, 146, 214])
MAX_RECEIVE_BYTE_NB = 2**16


class AsyncPipeServer(AsyncServer):
    def __init__(self, room_factory: Callable[[str], Room] = Room) -> None:
        super().__init__(room_factory=room_factory)

    async def __aenter__(self) -> AsyncPipeServer:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            await exit_stack.enter_async_context(self.room_manager)
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

    async def connect(self, id: str, server_sender=None, server_receiver=None):
        client_sender = None
        if server_sender is None:
            client_receiver, server_sender = os.pipe()
            server_receiver, client_sender = os.pipe()
            # os.set_inheritable(client_receiver, True)
            # os.set_inheritable(client_sender, True)
            # os.set_inheritable(server_sender, True)
        channel = Pipe(self._task_group, server_sender, server_receiver, id)
        room = await self.room_manager.get_room(id)
        await self._task_group.start(room.serve, channel)
        if client_sender is not None:
            return client_sender, client_receiver, server_sender, server_receiver


class Pipe(AsyncChannel):
    def __init__(self, tg: TaskGroup, sender: int, receiver: int, id: str):
        self._sender = sender
        self._receiver = receiver
        self._send_stream, receive_stream = create_memory_object_stream[bytes](
            float("inf")
        )
        self._buffered_stream = BufferedByteReceiveStream(receive_stream)
        self._id = id
        self._send_lock = Lock()
        self._receive_lock = Lock()
        tg.start_soon(partial(to_thread.run_sync, self._run, abandon_on_cancel=True))

    async def __anext__(self) -> bytes:
        try:
            message = await self.receive()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def id(self) -> str:
        return self._id  # pragma: nocover

    async def send(self, message: bytes):
        msg = message + SEPARATOR
        nb = 0
        while nb != len(msg):
            msg = msg[nb:]
            nb = os.write(self._sender, msg)

    def _run(self) -> None:
        while True:
            message = os.read(self._receiver, MAX_RECEIVE_BYTE_NB)
            if STOP in message:
                return
            from_thread.run_sync(self._send_stream.send_nowait, message)

    async def receive(self) -> bytes:
        return await self._buffered_stream.receive_until(SEPARATOR, MAX_RECEIVE_BYTE_NB)
