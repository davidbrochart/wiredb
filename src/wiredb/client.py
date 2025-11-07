from __future__ import annotations

import sys
from contextlib import AsyncExitStack
from importlib.metadata import entry_points
from types import TracebackType
from typing import Any

from anyio import Event, TASK_STATUS_IGNORED, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Doc, TransactionEvent, YMessageType, YSyncMessageType, create_sync_message, create_update_message, handle_sync_message

from .channel import Channel

if sys.version_info >= (3, 11):
    pass
else:  # pragma: nocover
    pass


class ClientWire:
    channel: Channel

    def __init__(self, doc: Doc | None = None, auto_push: bool = True, auto_pull: bool = True) -> None:
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

    @property
    def synchronized(self) -> Event:
        return self._synchronized

    def pull(self) -> None:
        """
        If the client was created with `auto_pull=False`, applies the received updates
        to the shared document.
        """
        if self._is_async:
            self._pull_event.set()
        else:
            self._pull()

    def push(self) -> None:
        """
        If the client was created with `auto_push=False`, sends the updates made to the
        shared document locally.
        """
        if self._is_async:
            self._push_event.set()
        else:
            self._send_updates(True)

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

    @property
    def doc(self) -> Doc:
        return self._doc

    async def _arun(self):
        await self._wait_pull()
        self._synchronizing = True
        async with self._doc.new_transaction():
            sync_message = create_sync_message(self._doc)
        await self.channel.asend(sync_message)
        async for message in self.channel:
            if message[0] == YMessageType.SYNC:
                await self._wait_pull()
                async with self._doc.new_transaction():
                    reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    await self.channel.asend(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    await self._task_group.start(self._asend_updates)
                    self._synchronizing = False

    async def _asend_updates(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
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
                await self.channel.asend(message)

    def _pull(self) -> bool:
        while True:
            try:
                message = self.channel.recv()
            except Exception:
                return False

            if message[0] == YMessageType.SYNC:
                reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    self.channel.send(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    return True
                return False

    def _store_updates(self, event: TransactionEvent) -> None:
        self._updates.append(event.update)
        self._send_updates()

    def _send_updates(self, do_send: bool = False) -> None:
        if do_send or self._auto_push:
            for update in self._updates:
                message = create_update_message(update)
                self.channel.send(message)
            self._updates.clear()

    def __enter__(self) -> ClientWire:
        self._is_async = False
        self._updates: list[bytes] = []
        self.subscription = self._doc.observe(self._store_updates)
        sync_message = create_sync_message(self._doc)
        self.channel.send(sync_message)
        while not self._pull():
            pass
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._doc.unobserve(self.subscription)
        return None

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            self._is_async = True
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            self._task_group.start_soon(self._arun)
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


def connect(wire: str, *, id: str = "", doc: Doc | None = None, auto_push: bool = True, auto_pull: bool = True, **kwargs: Any) -> ClientWire:
    """
    Creates a client using a `wire`, and its specific arguments. The client must always
    be used with an async context manager, for instance:
    ```py
    async with connect("websocket", host="localhost", port=8000) as client:
        ...
    ```

    Args:
        wire: The wire used to connect.
        id: The ID of the room to connect to in the server.
        doc: An optional external shared document (or a new one will be created).
        auto_push: Whether to automatically send updates of the shared document as they
            are made by this client. If `False`, the client can use the `push()` client methods
            to send the local updates.
        auto_pull: Whether to automatically apply updates to the shared document
            as they are received. If `False`, the client can use the `pull()`
            client methods to apply the remote updates.
        kwargs: The arguments that are specific to the wire.

    Returns:
        The created client.
    """
    eps = entry_points(group="wires")
    try:
        _Wire = eps[f"{wire}_client"].load()
    except KeyError:
        raise RuntimeError(f'No client found for "{wire}", did you forget to install "wire-{wire}"?')
    return _Wire(id, doc, auto_push, auto_pull, **kwargs)
