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

    def __init__(self, doc: Doc | None = None, auto_update: bool = True) -> None:
        self._doc: Doc = Doc() if doc is None else doc
        self._auto_update = auto_update
        self._pull_event = Event()
        self._push_event = Event()
        self._handshaking = False
        self._ready = Event()

    def pull(self) -> None:
        """
        If the client was created with `auto_update=False`, applies the received updates
        to the shared document.
        """
        if self._is_async:
            self._pull_event.set()
        else:
            self._pull()

    def push(self) -> None:
        """
        If the client was created with `auto_update=False`, sends the updates made to the
        shared document locally.
        """
        self._push_event.set()

    async def _wait_pull(self) -> None:
        if self._auto_update:
            return

        if not self._handshaking:
            await self._pull_event.wait()
            self._pull_event = Event()

    async def _wait_push(self) -> None:
        if self._auto_update:
            return

        await self._push_event.wait()
        self._push_event = Event()

    @property
    def doc(self) -> Doc:
        return self._doc

    async def _arun(self):
        if not self._auto_update:
            self._ready.set()
        await self._wait_pull()
        self._handshaking = True
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
                    await self._task_group.start(self._send_updates)
                    self._handshaking = False

    async def _send_updates(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with self._doc.events() as events:
            self._ready.set()
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

    def _send_update(self, event: TransactionEvent) -> None:
        message = create_update_message(event.update)
        self.channel.send(message)

    def __enter__(self) -> ClientWire:
        self._is_async = False
        self.subscription = self._doc.observe(self._send_update)
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


def connect(wire: str, *, id: str = "", doc: Doc | None = None, auto_update: bool = True, **kwargs: Any) -> ClientWire:
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
        auto_update: Whether to automatically apply updates to the shared document
            as they are received, and send updates of the shared document as they
            are made by this client. If `False`, the client can use the `pull()` and
            `push()` client methods to apply the remote updates and send the local updates,
            respectively.
        kwargs: The arguments that are specific to the wire.

    Returns:
        The created client.
    """
    eps = entry_points(group="wires")
    try:
        _Wire = eps[f"{wire}_client"].load()
    except KeyError:
        raise RuntimeError(f'No client found for "{wire}", did you forget to install "wire-{wire}"?')
    return _Wire(id, doc, auto_update, **kwargs)
