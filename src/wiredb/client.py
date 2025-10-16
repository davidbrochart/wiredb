from __future__ import annotations

from abc import ABC, abstractmethod
from contextlib import AsyncExitStack
from importlib.metadata import entry_points

from anyio import Event, create_task_group
from pycrdt import Channel, Doc, YMessageType, create_sync_message, create_update_message, handle_sync_message


class ClientWire(ABC):
    def __init__(self) -> None:
        self._doc: Doc = Doc()

    @property
    def doc(self) -> Doc:
        return self._doc

    @abstractmethod
    async def __aenter__(self) -> ClientWire: ...

    @abstractmethod
    async def __aexit__(self, exc_type, exc_value, exc_tb) -> bool | None: ...


def connect(wire: str, *, id: str = "", **kwargs) -> ClientWire:
    eps = entry_points(group="wires")
    _Wire = eps[f"{wire}_client"].load()
    return _Wire(id, **kwargs)


class Provider:
    def __init__(self, doc: Doc, channel: Channel) -> None:
        self._doc = doc
        self._channel = channel
        self._ready = Event()

    async def _run(self):
        async with self._doc.new_transaction():
            sync_message = create_sync_message(self._doc)
        await self._channel.send(sync_message)
        self._task_group.start_soon(self._send_updates)
        async for message in self._channel:
            if message[0] == YMessageType.SYNC:
                async with self._doc.new_transaction():
                    reply = handle_sync_message(message[1:], self._doc)
                if reply is not None:
                    await self._channel.send(reply)
                    self._ready.set()

    async def _send_updates(self):
        async with self._doc.events() as events:
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
