from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from importlib.metadata import entry_points
from types import TracebackType

from anyio import Lock, TASK_STATUS_IGNORED, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Channel, Doc, YMessageType, create_sync_message, create_update_message, handle_sync_message


class ServerWire(ABC):
    _room_manager = None

    @property
    def room_manager(self) -> RoomManager:
        if self._room_manager is None:
            self._room_manager = RoomManager()
        return self._room_manager

    @room_manager.setter
    def room_manager(self, value: RoomManager) -> None:
        self._room_manager = value

    @abstractmethod
    async def __aenter__(self) -> ServerWire: ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_value, exc_tb) -> bool | None: ...


def bind(wire: str, **kwargs) -> ServerWire:
    eps = entry_points(group="wires")
    _Wire = eps[f"{wire}_server"].load()
    return _Wire(**kwargs)


class Room:
    def __init__(self, id: str) -> None:
        self._id = id
        self._doc: Doc = Doc()
        self._clients: set[Channel] = set()

    @property
    def doc(self) -> Doc:
        return self._doc

    async def start(self, *, task_status: TaskStatus[None]):
        async with self._doc.events() as events:
            task_status.started()
            async for event in events:
                if self._clients:
                    message = create_update_message(event.update)
                    clients = set(self._clients)
                    for client in clients:
                        try:
                            await client.send(message)
                        except BaseException:
                            self._clients.discard(client)

    async def serve(self, client: Channel, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        self._clients.add(client)
        started = False
        try:
            async with self._doc.new_transaction():
                sync_message = create_sync_message(self._doc)
            await client.send(sync_message)
            task_status.started()
            started = True
            async for message in client:
                message_type = message[0]
                if message_type == YMessageType.SYNC:
                    async with self._doc.new_transaction():
                        reply = handle_sync_message(message[1:], self._doc)
                    if reply is not None:
                        await client.send(reply)
        except BaseException:
            if not started:
                task_status.started()
            self._clients.discard(client)


class RoomManager:
    def __init__(self, room_type: type[Room] = Room) -> None:
        self._room_type = room_type
        self._rooms: dict[str, Room] = {}
        self._lock = Lock()

    async def __aenter__(self) -> RoomManager:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
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

    async def get_room(self, id: str) -> Room:
        async with self._lock:
            if id not in self._rooms:
                room = self._room_type(id)
                await self._task_group.start(room.start)
                self._rooms[id] = room
            else:
                room = self._rooms[id]
        return room
