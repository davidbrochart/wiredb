from __future__ import annotations

import math
from collections.abc import Callable
from contextlib import AsyncExitStack
from types import TracebackType

from anyio import Lock, create_task_group, create_memory_object_stream

from wiredb import Channel, Room, ServerWire as _ServerWire


class ServerWire(_ServerWire):
    def __init__(self, room_factory: Callable[[str], Room] = Room) -> None:
        super().__init__(room_factory=room_factory)

    async def __aenter__(self) -> ServerWire:
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
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def connect(self, id: str):
        server_send_stream, client_receive_stream = create_memory_object_stream[bytes](max_buffer_size=math.inf)
        client_send_stream, server_receive_stream = create_memory_object_stream[bytes](max_buffer_size=math.inf)
        channel = Memory(server_send_stream, server_receive_stream, id)
        room = await self.room_manager.get_room(id)
        self._task_group.start_soon(self._serve, room, channel)
        return client_send_stream, client_receive_stream

    async def _serve(self, room: Room, channel: Memory):
        async with (
            channel.send_stream as channel.send_stream,
            channel.receive_stream as channel.receive_stream
        ):
            await room.serve(channel)


class Memory(Channel):
    def __init__(self, send_stream, receive_stream, path: str):
        self.send_stream = send_stream
        self.receive_stream = receive_stream
        self._path = path
        self._send_lock = Lock()
        self.send_nb = 0
        self.receive_nb = 0

    async def __anext__(self) -> bytes:
        try:
            message = await self.arecv()
        except Exception:
            raise StopAsyncIteration()

        return message

    @property
    def path(self) -> str:
        return self._path  # pragma: nocover

    async def asend(self, message: bytes):
        async with self._send_lock:
            await self.send_stream.send(message)
            self.send_nb += 1

    async def arecv(self) -> bytes:
        message = await self.receive_stream.receive()
        self.receive_nb += 1
        return message
