from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from types import TracebackType

from anyio import Event, create_task_group
from anyio.abc import TaskStatus
from pycrdt import (
    Doc,
    Subscription,
    TransactionEvent,
    YMessageType,
    YSyncMessageType,
    create_sync_message,
    create_update_message,
    handle_sync_message,
)

from .channel import AsyncChannel, Channel

if sys.version_info >= (3, 11):
    pass
else:  # pragma: nocover
    pass


class ClientMixin:
    _client: Client

    @property
    def doc(self) -> Doc:
        return self._client._doc

    def push(self) -> None:
        self._client.push()

    def pull(self) -> None:
        self._client.pull()

    @property
    def synchronized(self) -> bool:
        return self._client._synchronized


class AsyncClientMixin:
    _client: AsyncClient

    @property
    def doc(self) -> Doc:
        return self._client._doc

    def push(self) -> None:
        self._client.push()

    def pull(self) -> None:
        self._client.pull()

    @property
    def synchronized(self) -> Event:
        return self._client._synchronized


class Client:
    def __init__(
        self, channel: Channel, doc: Doc | None = None, auto_push: bool = False
    ) -> None:
        """
        Creates a client that connects to a server. The client must always
        be used with a context manager, for instance:
        ```py
        with WebsocketClient(host="localhost", port=8000) as client:
            ...
        ```

        Args:
            channel: The channel used to communicate with the server.
            doc: An optional external shared document (or a new one will be created).
            auto_push: Whether to automatically send updates of the shared document as they
                are made by this client. If `False`, the client can use the `push()` method
                to send the local updates.
        """
        self._channel = channel
        self._doc: Doc = Doc() if doc is None else doc
        self._auto_push = auto_push
        self._synchronizing = False
        self._synchronized = False
        self._subscription: Subscription | None = None

    @property
    def synchronized(self) -> bool:  # pragma: nocover
        return self._synchronized

    def pull(self) -> None:
        """
        Applies the received updates to the shared document.
        """
        self._pull()

    def push(self) -> None:  # pragma: nocover
        """
        If the client was created with `auto_push=False`, sends the updates made to the
        shared document locally.
        """
        self._send_updates(True)

    def _pull(self) -> None:
        if not self._synchronizing and not self._synchronized:
            self._synchronizing = True
            sync_message = create_sync_message(self._doc)
            self._channel.send(sync_message)

        timeout = None if self._synchronizing else 0

        while True:
            try:
                message = self._channel.receive(timeout)
            except TimeoutError:
                return

            if message[0] == YMessageType.SYNC:
                reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    self._channel.send(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    self._synchronized = True
                    self._synchronizing = False
                    self._subscription = self._doc.observe(self._store_updates)
                    return

    def _store_updates(self, event: TransactionEvent) -> None:
        self._updates.append(event.update)
        self._send_updates()

    def _send_updates(self, push: bool = False) -> None:
        if push or self._auto_push:
            for update in self._updates:
                message = create_update_message(update)
                self._channel.send(message)
            self._updates.clear()

    def __enter__(self) -> "Client":
        self._updates: list[bytes] = []
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        if self._subscription is not None:
            self._doc.unobserve(self._subscription)
        return None


class AsyncClient:
    def __init__(
        self,
        channel: AsyncChannel,
        doc: Doc | None = None,
        auto_push: bool = True,
        auto_pull: bool = True,
    ) -> None:
        """
        Creates an async client that connects to a server. The client must always
        be used with an async context manager, for instance:
        ```py
        async with AsyncWebsocketClient(host="localhost", port=8000) as client:
            ...
        ```

        Args:
            channel: The async channel used to communicate with the server.
            doc: An optional external shared document (or a new one will be created).
            auto_push: Whether to automatically send updates of the shared document as they
                are made by this client. If `False`, the client can use the `push()` method
                to send the local updates.
            auto_pull: Whether to automatically apply updates to the shared document
                as they are received. If `False`, the client can use the `pull()`
                method to apply the remote updates.
        """
        self._channel = channel
        self._doc: Doc = Doc() if doc is None else doc
        self._auto_push = auto_push
        self._auto_pull = auto_pull
        self._pull_event = Event()
        self._push_event = Event()
        self._synchronizing = False
        self._synchronized = Event()
        self._ready = Event()
        if not auto_pull:
            self._ready.set()

    def pull(self) -> None:
        """
        If the client was created with `auto_pull=False`, applies the received updates
        to the shared document.
        """
        self._pull_event.set()

    def push(self) -> None:
        """
        If the client was created with `auto_push=False`, sends the updates made to the
        shared document locally.
        """
        self._push_event.set()

    async def _wait_pull(self) -> None:
        if self._auto_pull:
            return

        if not self._synchronizing:
            await self._pull_event.wait()
            self._pull_event = Event()

    async def _wait_push(self) -> None:
        if self._auto_push:
            return

        await self._push_event.wait()
        self._push_event = Event()

    async def _run(self):
        await self._wait_pull()
        self._synchronizing = True
        async with self._doc.new_transaction():
            sync_message = create_sync_message(self._doc)
        await self._channel.send(sync_message)
        async for message in self._channel:
            if message[0] == YMessageType.SYNC:
                await self._wait_pull()
                async with self._doc.new_transaction():
                    reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    await self._channel.send(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    await self._task_group.start(self._send_updates)
                    self._synchronizing = False

    async def _send_updates(self, *, task_status: TaskStatus[None]):
        async with self._doc.events() as events:
            self._ready.set()
            self._synchronized.set()
            task_status.started()
            update_nb = 0
            async for event in events:
                if update_nb == 0:
                    await self._wait_push()
                    update_nb = events.statistics().current_buffer_used
                else:
                    update_nb -= 1
                message = create_update_message(event.update)
                await self._channel.send(message)

    async def __aenter__(self) -> "AsyncClient":
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            self._task_group.start_soon(self._run)
            await self._ready.wait()
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
