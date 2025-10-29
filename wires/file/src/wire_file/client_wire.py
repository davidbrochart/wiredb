from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import anyio
from anyio import AsyncContextManagerMixin, AsyncFile, CancelScope, Lock, TASK_STATUS_IGNORED, create_memory_object_stream, create_task_group, open_file, sleep
from anyio.abc import TaskGroup, TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pycrdt import Channel, Decoder, Doc, YMessageType, YSyncMessageType, create_sync_message, handle_sync_message, write_message

from wiredb import Provider, ClientWire as _ClientWire

if sys.version_info >= (3, 11):
    from typing import Self
else:  # pragma: nocover
    from typing_extensions import Self


class ClientWire(AsyncContextManagerMixin, _ClientWire):
    def __init__(
        self,
        id: str,
        doc: Doc | None = None,
        auto_update: bool = True,
        *,
        path: Path | str,
        write_delay: float = 0,
        squash: bool = False,
    ) -> None:
        super().__init__(doc, auto_update)
        self._id = id
        self._path: anyio.Path = anyio.Path(path)
        self._write_delay = write_delay
        self._squash = squash
        self._version = "0.0.1"
        self._lock = Lock()

    @property
    def version(self) -> str:
        return self._version

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        file_doc: Doc = Doc()
        size = len(self._version) + 1
        if file_exists := await self._path.exists():
            file_version, messages = await read_file(self._path, self._lock)
            if file_version != self._version:
                raise RuntimeError(f'File version mismatch (got "{file_version}", expected "{self._version}")')
            size += len(messages)
            decoder = Decoder(messages)
            while True:
                update = decoder.read_message()
                if not update:
                    break
                file_doc.apply_update(update)
        async with file_doc.new_transaction():
            sync_message = create_sync_message(file_doc)
        async with await open_file(self._path, mode="a+b", buffering=0) as self._file:
            if not file_exists:
                with CancelScope(shield=True):
                    await write_file(self._file, self._version.encode() + bytes([0]), self._lock)
            elif self._squash:
                await squash_file(self._file, self._lock)
            send_stream, receive_stream = create_memory_object_stream[bytes](max_buffer_size=float("inf"))
            async with send_stream, receive_stream, create_task_group() as tg:
                await send_stream.send(sync_message)
                self.channel = File(self._file, self._id, file_doc, send_stream, receive_stream, tg, self._write_delay, size, self._squash, self._version, self._lock)
                async with Provider(self):
                    yield self
                    tg.cancel_scope.cancel()


class File(Channel):
    def __init__(
        self,
        file: AsyncFile[bytes],
        path: str,
        file_doc: Doc,
        send_stream: MemoryObjectSendStream[bytes],
        receive_stream: MemoryObjectReceiveStream[bytes],
        task_group: TaskGroup,
        write_delay: float,
        size: int,
        squash: bool,
        version: str,
        lock: Lock,
    ) -> None:
        self._file = file
        self._path = path
        self._file_doc: Doc | None = file_doc
        self._send_stream = send_stream
        self._receive_stream = receive_stream
        self._task_group = task_group
        self._write_delay = write_delay
        self._squash = squash
        self._version = version
        self._lock = lock
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
                    update = message[2:]
                    if update != bytes([2, 0, 0]):
                        self._messages.append(update)
                        await self._task_group.start(self._write_updates)
                    self._file_doc = None

    async def recv(self) -> bytes:
        message = await self._receive_stream.receive()
        return message

    async def _write_updates(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        with CancelScope() as self._write_cancel_scope:
            task_status.started()
            await sleep(self._write_delay)
            with CancelScope(shield=True):
                messages = b"".join(self._messages)
                self._messages.clear()
                self._write_cancel_scope = None
                if self._squash:
                    await squash_file(self._file, self._lock, messages)
                else:
                    await write_file(self._file, messages, self._lock)


async def read_file(path: anyio.Path, lock: Lock) -> tuple[str, bytes]:
    async with lock:
        data = await path.read_bytes()
        version, messages = data.split(bytes([0]), 1)
        return version.decode(), messages


async def write_file(file: AsyncFile[bytes], data: bytes, lock: Lock) -> None:
    async with lock:
        await file.write(data)


async def squash_file(file: AsyncFile[bytes], lock: Lock, with_messages: bytes | None = None) -> None:
    async with lock:
        await file.seek(0)
        data = await file.read()
        version, messages = data.split(bytes([0]), 1)
        header_size = len(version) + 1
        await file.truncate(header_size)
        file_doc: Doc = Doc()
        if with_messages is not None:
            messages += with_messages
        decoder = Decoder(messages)
        while True:
            update = decoder.read_message()
            if not update:
                break
            file_doc.apply_update(update)
        squashed_update = file_doc.get_update()
        message = write_message(squashed_update)
        await file.write(message)
