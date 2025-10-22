from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager
from importlib.metadata import entry_points

from anyio import AsyncContextManagerMixin, Lock, TASK_STATUS_IGNORED, create_task_group, get_cancelled_exc_class, sleep_forever
from anyio.abc import TaskGroup, TaskStatus
from pycrdt import Channel, Doc, YMessageType, create_sync_message, create_update_message, handle_sync_message

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: nocover
    from typing_extensions import Self


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
    try:
        _Wire = eps[f"{wire}_server"].load()
    except KeyError:
        raise RuntimeError(f'No server found for "{wire}", did you forget to install "wire-{wire}"?')
    return _Wire(**kwargs)


class Room(AsyncContextManagerMixin):
    def __init__(self, id: str) -> None:
        self._id = id
        self._doc: Doc = Doc()
        self._clients: set[Channel] = set()

    @property
    def id(self) -> str:
        return self._id

    @property
    def doc(self) -> Doc:
        return self._doc

    @property
    def task_group(self) -> TaskGroup:
        return self._task_group

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as self._task_group:
            await self._task_group.start(self.run)
            yield self

    async def run(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with self._doc.events() as events:
            task_status.started()
            async for event in events:
                if self._clients:
                    message = create_update_message(event.update)
                    clients = set(self._clients)
                    for client in clients:
                        try:
                            await client.send(message)
                        except get_cancelled_exc_class():  # pragma: nocover
                            self._clients.discard(client)
                            raise
                        except BaseException:  # pragma: nocover
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
        except get_cancelled_exc_class():
            raise
        except BaseException:  # pragma: nocover
            pass
        finally:
            if not started:  # pragma: nocover
                task_status.started()
            self._clients.discard(client)


class RoomManager(AsyncContextManagerMixin):
    def __init__(self, room_factory: Callable[[str], Room] = Room) -> None:
        self._room_factory = room_factory
        self._rooms: dict[str, Room] = {}
        self._lock = Lock()

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as self._task_group:
            yield self
            self._task_group.cancel_scope.cancel()

    async def _create_room(self, id: str, *, task_status: TaskStatus[Room]):
        async with self._room_factory(id) as room:
            task_status.started(room)
            await sleep_forever()

    async def get_room(self, id: str) -> Room:
        async with self._lock:
            if id not in self._rooms:
                room = await self._task_group.start(self._create_room, id)
                self._rooms[id] = room
            else:
                room = self._rooms[id]
        return room
