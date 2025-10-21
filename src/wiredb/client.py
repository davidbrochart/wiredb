from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from importlib.metadata import entry_points

from anyio import Event, TASK_STATUS_IGNORED, create_task_group
from anyio.abc import TaskStatus
from pycrdt import Channel, Doc, YMessageType, YSyncMessageType, create_sync_message, create_update_message, handle_sync_message


class ClientWire(ABC):
    def __init__(self, doc: Doc | None = None) -> None:
        self._doc: Doc = Doc() if doc is None else doc

    @property
    def doc(self) -> Doc:
        return self._doc

    @abstractmethod
    async def __aenter__(self) -> ClientWire: ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_value, exc_tb) -> bool | None: ...


def connect(wire: str, *, id: str = "", doc: Doc | None = None, **kwargs) -> ClientWire:
    eps = entry_points(group="wires")
    try:
        _Wire = eps[f"{wire}_client"].load()
    except KeyError:
        raise RuntimeError(f'No client found for "{wire}", did you forget to install "wire-{wire}"?')
    return _Wire(id, doc, **kwargs)


class Provider:
    def __init__(self, doc: Doc, channel: Channel) -> None:
        self._doc = doc
        self._channel = channel
        self._ready = Event()

    async def _run(self):
        async with self._doc.new_transaction():
            sync_message = create_sync_message(self._doc)
        await self._channel.send(sync_message)
        async for message in self._channel:
            if message[0] == YMessageType.SYNC:
                async with self._doc.new_transaction():
                    reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    await self._channel.send(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                   await self._task_group.start(self._send_updates)

    async def _send_updates(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        async with self._doc.events() as events:
            self._ready.set()
            task_status.started()
            async for event in events:
                message = create_update_message(event.update)
                await self._channel.send(message)

    async def __aenter__(self) -> Provider:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            self._task_group.start_soon(self._run)
            await self._ready.wait()
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(self, exc_type, exc_value, exc_tb) -> bool | None:
        self._task_group.cancel_scope.cancel()
        return await self._exit_stack.__aexit__(exc_type, exc_value, exc_tb)
