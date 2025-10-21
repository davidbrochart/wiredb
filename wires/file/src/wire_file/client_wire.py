from __future__ import annotations

from contextlib import AsyncExitStack
from pathlib import Path
from types import TracebackType

import anyio
from anyio import CancelScope, TASK_STATUS_IGNORED, create_memory_object_stream, create_task_group, open_file, sleep
from anyio.abc import TaskGroup, TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pycrdt import Channel, Decoder, Doc, YMessageType, YSyncMessageType, create_sync_message, handle_sync_message

from wiredb import Provider, ClientWire as _ClientWire


class ClientWire(_ClientWire):
    def __init__(self, id: str, doc: Doc | None = None, *, path: Path | str, write_delay: float = 0) -> None:
        super().__init__(doc)
        self._id = id
        self._path: anyio.Path = anyio.Path(path)
        self._write_delay = write_delay

    async def __aenter__(self) -> ClientWire:
        async with AsyncExitStack() as exit_stack:
            file_doc: Doc = Doc()
            if await self._path.exists():
                updates = await self._path.read_bytes()
                decoder = Decoder(updates)
                while True:
                    update = decoder.read_message()
                    if not update:
                        break
                    file_doc.apply_update(update)
            async with file_doc.new_transaction():
                sync_message = create_sync_message(file_doc)
            self._file = await exit_stack.enter_async_context(
                await open_file(self._path, mode="ab", buffering=0)
            )
            send_stream, receive_stream = create_memory_object_stream[bytes](max_buffer_size=float("inf"))
            send_stream = await exit_stack.enter_async_context(send_stream)
            await send_stream.send(sync_message)
            receive_stream = await exit_stack.enter_async_context(receive_stream)
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            channel = File(self._file, self._id, file_doc, send_stream, receive_stream, self._task_group, self._write_delay)
            await exit_stack.enter_async_context(Provider(self._doc, channel))
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


class File(Channel):
    def __init__(
        self,
        file: anyio.AsyncFile[bytes],
        path: str,
        file_doc: Doc,
        send_stream: MemoryObjectSendStream[bytes],
        receive_stream: MemoryObjectReceiveStream[bytes],
        task_group: TaskGroup,
        write_delay: float,
    ) -> None:
        self._file = file
        self._path = path
        self._file_doc: Doc | None = file_doc
        self._send_stream = send_stream
        self._receive_stream = receive_stream
        self._write_delay = write_delay
        self._task_group = task_group
        self._messages: list[bytes] = []
        self._write_cancel_scope: CancelScope | None = None

    async def __anext__(self) -> bytes:
        try:
            message = await self.recv()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def path(self) -> str:
        return self._path  # pragma: nocover

    async def send(self, message: bytes) -> None:
        message_type = message[0]
        if message_type == YMessageType.SYNC:
            if message[1] == YSyncMessageType.SYNC_UPDATE:
                if self._write_cancel_scope is not None:
                    self._write_cancel_scope.cancel()
                self._messages.append(message[2:])
                await self._task_group.start(self._write_updates)
            else:
                assert self._file_doc is not None
                async with self._file_doc.new_transaction():
                    reply = handle_sync_message(message[1:], self._file_doc)
                if reply is not None:
                    await self._send_stream.send(reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    self._file_doc = None

    async def recv(self) -> bytes:
        message = await self._receive_stream.receive()
        return message

    async def _write_updates(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        with CancelScope() as self._write_cancel_scope:
            task_status.started()
            await sleep(self._write_delay)
            data = b"".join(self._messages)
            self._messages.clear()
            self._write_cancel_scope = None
            with CancelScope(shield=True):
                await self._file.write(data)
