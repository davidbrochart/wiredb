from __future__ import annotations

import sys
from contextlib import AsyncExitStack, ExitStack
from io import FileIO
from pathlib import Path
from types import TracebackType

import anyio
from anyio import (
    TASK_STATUS_IGNORED,
    CancelScope,
    Lock,
    create_memory_object_stream,
    create_task_group,
    open_file,
    sleep,
)
from anyio.abc import TaskGroup, TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
from pycrdt import (
    Decoder,
    Doc,
    YMessageType,
    YSyncMessageType,
    create_sync_message,
    handle_sync_message,
    write_message,
)

from wiredb import (
    AsyncChannel,
    AsyncClient,
    AsyncClientMixin,
    Channel,
    Client,
    ClientMixin,
)

if sys.version_info >= (3, 11):
    pass
else:  # pragma: nocover
    pass


class FileClient(ClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = False,
        *,
        path: Path | str,
        write_delay: float = 0,
        squash: bool = False,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
        self._path: Path = Path(path)
        self._write_delay = write_delay
        self._squash = squash
        self._version = "0.0.1"
        self._lock = Lock()

    @property
    def version(self) -> str:  # pragma: nocover
        return self._version

    def __enter__(self) -> FileClient:
        with ExitStack() as exit_stack:
            file_doc: Doc = Doc()
            size = len(self._version) + 1
            if file_exists := self._path.exists():
                file_version, messages = read_file(self._path)
                if file_version != self._version:  # pragma: nocover
                    raise RuntimeError(
                        f'File version mismatch (got "{file_version}", expected "{self._version}")'
                    )
                size += len(messages)
                decoder = Decoder(messages)
                while True:
                    update = decoder.read_message()
                    if not update:
                        break
                    file_doc.apply_update(update)
            sync_message = create_sync_message(file_doc)
            self._file = exit_stack.enter_context(
                open(self._path, mode="a+b", buffering=0)
            )
            if not file_exists:
                write_file(self._file, self._version.encode() + bytes([0]))
            elif self._squash:  # pragma: nocover
                squash_file(self._file)
            message_list = [sync_message]
            channel = File(
                self._file,
                self._id,
                file_doc,
                self._write_delay,
                size,
                self._squash,
                self._version,
                message_list=message_list,
            )
            self._client = exit_stack.enter_context(
                Client(channel, self._doc, self._auto_push)
            )
            self._exit_stack = exit_stack.pop_all()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return self._exit_stack.__exit__(exc_type, exc_val, exc_tb)


class AsyncFileClient(AsyncClientMixin):
    def __init__(
        self,
        id: str = "",
        doc: Doc | None = None,
        auto_push: bool = True,
        auto_pull: bool = True,
        *,
        path: Path | str,
        write_delay: float = 0,
        squash: bool = False,
    ) -> None:
        self._id = id
        self._doc = doc
        self._auto_push = auto_push
        self._auto_pull = auto_pull
        self._path: Path = Path(path)
        self._write_delay = write_delay
        self._squash = squash
        self._version = "0.0.1"
        self._lock = Lock()

    @property
    def version(self) -> str:
        return self._version

    async def __aenter__(self) -> "AsyncFileClient":
        async with AsyncExitStack() as exit_stack:
            path = anyio.Path(self._path)
            file_doc: Doc = Doc()
            size = len(self._version) + 1
            if file_exists := await path.exists():
                file_version, messages = await aread_file(path, self._lock)
                if file_version != self._version:
                    raise RuntimeError(
                        f'File version mismatch (got "{file_version}", expected "{self._version}")'
                    )
                size += len(messages)
                decoder = Decoder(messages)
                while True:
                    update = decoder.read_message()
                    if not update:
                        break
                    file_doc.apply_update(update)
            async with file_doc.new_transaction():
                sync_message = create_sync_message(file_doc)
            self._file = await exit_stack.enter_async_context(
                await open_file(path, mode="a+b", buffering=0)
            )
            if not file_exists:
                with CancelScope(shield=True):
                    await awrite_file(
                        self._file, self._version.encode() + bytes([0]), self._lock
                    )
            elif self._squash:
                await asquash_file(self._file, self._lock)
            send_stream, receive_stream = create_memory_object_stream[bytes](
                max_buffer_size=float("inf")
            )
            send_stream = await exit_stack.enter_async_context(send_stream)
            receive_stream = await exit_stack.enter_async_context(receive_stream)
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            await send_stream.send(sync_message)
            channel = AsyncFile(
                self._file,
                self._id,
                file_doc,
                self._write_delay,
                size,
                self._squash,
                self._version,
                send_stream=send_stream,
                receive_stream=receive_stream,
                task_group=self._task_group,
                lock=self._lock,
            )
            self._client = await exit_stack.enter_async_context(
                AsyncClient(channel, self._doc, self._auto_push, self._auto_pull)
            )
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
        file: FileIO,
        path: str,
        file_doc: Doc,
        write_delay: float,
        size: int,
        squash: bool,
        version: str,
        *,
        message_list: list[bytes] | None = None,
    ) -> None:
        self._file = file
        self._path = path
        self._file_doc: Doc | None = file_doc
        self._message_list = message_list
        self._write_delay = write_delay
        self._squash = squash
        self._version = version
        self._messages: list[bytes] = []

    @property
    def id(self) -> str:
        return self._path  # pragma: nocover

    def send(self, message: bytes) -> None:
        assert self._message_list is not None
        message_type = message[0]
        if message_type == YMessageType.SYNC:
            if message[1] == YSyncMessageType.SYNC_UPDATE:  # pragma: nocover
                self._messages.append(message[2:])
                self._write_updates()
            else:
                assert self._file_doc is not None
                reply = handle_sync_message(message[1:], self._file_doc)
                if reply is not None:
                    self._message_list.insert(0, reply)
                if message[1] == YSyncMessageType.SYNC_STEP2:
                    update = message[2:]
                    if update != bytes([2, 0, 0]):  # pragma: nocover
                        self._messages.append(update)
                        self._write_updates()
                    self._file_doc = None

    def receive(self, timeout: float | None = None) -> bytes:
        if not self._message_list:  # pragma: nocover
            raise TimeoutError()

        return self._message_list.pop()

    def _write_updates(self):
        messages = b"".join(self._messages)
        self._messages.clear()
        if self._squash:  # pragma: nocover
            squash_file(self._file, messages)
        else:
            write_file(self._file, messages)


class AsyncFile(AsyncChannel):
    def __init__(
        self,
        file: anyio.AsyncFile[bytes],
        path: str,
        file_doc: Doc,
        write_delay: float,
        size: int,
        squash: bool,
        version: str,
        *,
        message_list: list[bytes] | None = None,
        send_stream: MemoryObjectSendStream[bytes] | None = None,
        receive_stream: MemoryObjectReceiveStream[bytes] | None = None,
        task_group: TaskGroup | None = None,
        lock: Lock | None = None,
    ) -> None:
        self._file = file
        self._path = path
        self._file_doc: Doc | None = file_doc
        self._message_list = message_list
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
            message = await self.receive()
        except Exception:
            raise StopAsyncIteration()  # pragma: nocover

        return message

    @property
    def id(self) -> str:
        return self._path  # pragma: nocover

    async def send(self, message: bytes) -> None:
        assert self._task_group is not None
        assert self._send_stream is not None
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

    async def receive(self) -> bytes:
        assert self._receive_stream is not None
        return await self._receive_stream.receive()

    async def _write_updates(
        self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED
    ):
        assert self._lock is not None
        with CancelScope() as self._write_cancel_scope:
            task_status.started()
            await sleep(self._write_delay)
            with CancelScope(shield=True):
                messages = b"".join(self._messages)
                self._messages.clear()
                self._write_cancel_scope = None
                if self._squash:
                    await asquash_file(self._file, self._lock, messages)
                else:
                    await awrite_file(self._file, messages, self._lock)


def read_file(path: Path) -> tuple[str, bytes]:
    data = path.read_bytes()
    version, messages = data.split(bytes([0]), 1)
    return version.decode(), messages


async def aread_file(path: anyio.Path, lock: Lock) -> tuple[str, bytes]:
    async with lock:
        data = await path.read_bytes()
        version, messages = data.split(bytes([0]), 1)
        return version.decode(), messages


def write_file(file: FileIO, data: bytes) -> None:
    file.write(data)


async def awrite_file(file: anyio.AsyncFile[bytes], data: bytes, lock: Lock) -> None:
    async with lock:
        await file.write(data)


def squash_file(
    file: FileIO, with_messages: bytes | None = None
) -> None:  # pragma: nocover
    file.seek(0)
    data = file.read()
    version, messages = data.split(bytes([0]), 1)
    header_size = len(version) + 1
    file.truncate(header_size)
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
    file.write(message)


async def asquash_file(
    file: anyio.AsyncFile[bytes], lock: Lock, with_messages: bytes | None = None
) -> None:
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
