from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import AsyncExitStack
from functools import partial
from types import TracebackType

from anyio import Lock, create_memory_object_stream, create_task_group, from_thread, to_thread
from anyio.streams.buffered import BufferedByteReceiveStream

from wiredb import Channel, Room, ServerWire as _ServerWire

SEPARATOR = bytes([226, 164, 131, 121, 240, 77, 100, 52])
STOP = bytes([80, 131, 218, 244, 198, 47, 146, 214])
MAX_RECEIVE_BYTE_NB = 2 ** 16


class ServerWire(_ServerWire):
    def __init__(self, room_factory: Callable[[str], Room] = Room) -> None:
        super().__init__(room_factory=room_factory)

    async def __aenter__(self) -> ServerWire:
        async with AsyncExitStack() as exit_stack:
            self._self_senders: list[int] = []
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
        for sender in self._self_senders:
            try:
                os.fdopen(sender, "wb", buffering=0).write(STOP)
            except BaseException:  # pragma: nocover
                pass
        self._task_group.cancel_scope.cancel()
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def connect(self, id: str, server_sender=None, server_receiver=None):
        client_sender = None
        if server_sender is None:
            client_receiver, server_sender = os.pipe()
            server_receiver, client_sender = os.pipe()
            os.set_inheritable(client_receiver, True)
            os.set_inheritable(client_sender, True)
            os.set_inheritable(server_sender, True)
            self._self_senders.append(client_sender)
        channel = Pipe(self._task_group, server_sender, server_receiver, id)
        room = await self.room_manager.get_room(id)
        await self._task_group.start(room.serve, channel)
        if client_sender is not None:
            return client_sender, client_receiver, server_sender


class Pipe(Channel):
    def __init__(self, tg, sender, receiver, path: str):
        self._sender = os.fdopen(sender, "wb", buffering=0)
        self._receiver = os.fdopen(receiver, "rb", buffering=0)
        self._send_stream, receive_stream = create_memory_object_stream[bytes](float("inf"))
        self._buffered_stream = BufferedByteReceiveStream(receive_stream)
        self._path = path
        self._send_lock = Lock()
        self._receive_lock = Lock()
        tg.start_soon(partial(to_thread.run_sync, self._run, abandon_on_cancel=True))

    async def __anext__(self) -> bytes:
        try:
            message = await self.arecv()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def path(self) -> str:
        return self._path  # pragma: nocover

    async def asend(self, message: bytes):
        msg = message + SEPARATOR
        nb = 0
        while nb != len(msg):
            msg = msg[nb:]
            nb = self._sender.write(msg)

    def _run(self) -> None:
        while True:
            message = self._receiver.read(MAX_RECEIVE_BYTE_NB)
            if STOP in message:
                return
            from_thread.run_sync(self._send_stream.send_nowait, message)

    async def arecv(self) -> bytes:
        return await self._buffered_stream.receive_until(SEPARATOR, MAX_RECEIVE_BYTE_NB)
