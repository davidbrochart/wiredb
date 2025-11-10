from __future__ import annotations

import sys
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Callable
from contextlib import asynccontextmanager

from anyio import (
    TASK_STATUS_IGNORED,
    AsyncContextManagerMixin,
    Event,
    Lock,
    create_task_group,
    get_cancelled_exc_class,
)
from anyio.abc import TaskGroup, TaskStatus
from pycrdt import (
    Doc,
    YMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from .channel import AsyncChannel

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: nocover
    from typing_extensions import Self


class Room(AsyncContextManagerMixin):
    def __init__(self, id: str) -> None:
        """
        Creates a new room in which clients with the same ID will be connected.

        Args:
            id: The room ID.
        """
        self._id = id
        self._doc: Doc = Doc()
        self._clients: set[AsyncChannel] = set()
        self._clean_event = Event()

    @property
    def id(self) -> str:
        """
        Returns:
            The room ID.
        """
        return self._id

    @property
    def doc(self) -> Doc:
        """
        Returns:
            The room's shared document.
        """
        return self._doc

    @property
    def task_group(self) -> TaskGroup:
        """
        Returns:
            The room's task group, that can be used to launch background tasks.
        """
        return self._task_group

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as self._task_group:
            await self._task_group.start(self.run)
            yield self

    async def run(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        """
        The main background task which is responsible for forwarding every update
        from a client to all other clients in the room.

        Args:
            task_status: The task status that is set when the task has started.
        """
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
                            self._remove_client(client)
                            raise
                        except Exception:  # pragma: nocover
                            self._remove_client(client)

    async def serve(
        self,
        client: AsyncChannel,
        *,
        task_status: TaskStatus[None] = TASK_STATUS_IGNORED,
    ) -> None:
        """
        The handler for a client which is responsible for the connection handshake and for applying the client updates to the room's shared document.

        Args:
            client: The client making the connection.
            task_status: The task status that is set when the task has started.
        """
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
        finally:
            if not started:  # pragma: nocover
                task_status.started()
            self._remove_client(client)

    def _remove_client(self, client: AsyncChannel) -> None:
        self._clients.discard(client)
        if not self._clients:
            self._clean_event.set()


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
            await room._clean_event.wait()
            del self._rooms[id]

    async def get_room(self, id: str) -> Room:
        async with self._lock:
            if id not in self._rooms:
                room = await self._task_group.start(self._create_room, id)
                self._rooms[id] = room
            else:
                room = self._rooms[id]
        return room


class AsyncServer(ABC):
    def __init__(self, room_factory: Callable[[str], Room] = Room) -> None:
        """
        Creates an asynchronous server. The server must always
        be used with an async context manager, for instance:
        ```py
        async with AsyncWebsocketServer(host="localhost", port=8000) as server:
            ...
        ```

        Args:
            room_factory: An optional callable used to create a room.
        """
        self._room_manager = RoomManager(room_factory)

    @property
    def room_manager(self) -> RoomManager:
        return self._room_manager

    @abstractmethod
    async def __aenter__(self) -> "AsyncServer": ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_value, exc_tb) -> bool | None: ...
