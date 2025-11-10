import time
from collections.abc import Callable

import pytest

from anyio import TASK_STATUS_IGNORED, create_task_group, fail_after, sleep, sleep_forever
from anyio.abc import TaskStatus
from pycrdt import Doc, Text

from wiredb import Room
from wire_websocket import AsyncWebSocketServer, AsyncWebSocketClient, WebSocketClient


pytestmark = pytest.mark.anyio

async def test_server(free_tcp_port: int) -> None:
    async with AsyncWebSocketServer(host="localhost", port=free_tcp_port) as server:
        async with (
            AsyncWebSocketClient(host="http://localhost", port=free_tcp_port) as client0,
            AsyncWebSocketClient(host="http://localhost", port=free_tcp_port) as client1,
        ):
            assert len(server.room_manager._rooms) == 1
            text0 = client0.doc.get("text", type=Text)
            text1 = client1.doc.get("text", type=Text)
            text0 += "Hello"
            with fail_after(1):
                while True:
                    await sleep(0.01)
                    if str(text1) == "Hello":
                        break
            text1 += ", World!"
            with fail_after(1):
                while True:
                    await sleep(0.01)
                    if str(text0) == "Hello, World!":
                        break
        with fail_after(1):
            while True:
                await sleep(0.01)
                if len(server.room_manager._rooms) == 0:
                    break


async def test_multiple_servers(free_tcp_port_factory: Callable[[], int]) -> None:
    port0 = free_tcp_port_factory()
    port1 = free_tcp_port_factory()
    port2 = free_tcp_port_factory()

    class MyRoom(Room):
        async def run(self, *args, **kwargs) -> None:
            await self.task_group.start(self._connect_to_server)
            await super().run(*args, **kwargs)

        async def _connect_to_server(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
            async with AsyncWebSocketClient(id=self.id, doc=self.doc, host="http://localhost", port=port0):
                task_status.started()
                await sleep_forever()

    async def run_server(port: int, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED) -> None:
        if port != port0:
            server = AsyncWebSocketServer(room_factory=MyRoom, host="localhost", port=port)
        else:
            server = AsyncWebSocketServer(host="localhost", port=port)
        async with server:
            task_status.started()
            await sleep_forever()

    async def run_client(doc: Doc, port: int, message: str) -> None:
        async with AsyncWebSocketClient(doc=doc, host="http://localhost", port=port):
            text = doc.get("text", type=Text)
            text += message
            await sleep_forever()

    async with create_task_group() as tg:
        await tg.start(run_server, port0)
        await tg.start(run_server, port1)
        await tg.start(run_server, port2)
        doc1: Doc = Doc()
        doc2: Doc = Doc()
        tg.start_soon(run_client, doc1, port1, "Hello")
        tg.start_soon(run_client, doc2, port2, "World")

        text1 = doc1.get("text", type=Text)
        with fail_after(2):
            while True:
                await sleep(0.01)
                if "Hello" in str(text1) and "World" in str(text1):
                    break

        text2 = doc2.get("text", type=Text)
        with fail_after(2):
            while True:
                await sleep(0.01)
                if "Hello" in str(text2) and "World" in str(text2):
                    break

        tg.cancel_scope.cancel()


def test_server_sync_client(websocket_server) -> None:
    host, port = websocket_server
    with (
        WebSocketClient(host=f"http://{host}", port=port) as client0,
        WebSocketClient(host=f"http://{host}", auto_push=True, port=port) as client1,
    ):
        assert not client0.synchronized
        assert not client1.synchronized
        client0.pull()
        client1.pull()
        assert client0.synchronized
        assert client1.synchronized
        text0 = client0.doc.get("text", type=Text)
        text1 = client1.doc.get("text", type=Text)
        text0 += "Hello"
        time.sleep(0.1)
        assert str(text1) == ""
        client0.push()
        for i in range(10):
            time.sleep(0.1)
            client1.pull()
            if str(text1) == "Hello":
                break
        else:
            raise TimeoutError()  # pragma: nocover
        client1.pull()
        text1 += ", World!"
        for i in range(10):
            time.sleep(0.1)
            client0.pull()
            if str(text0) == "Hello, World!":
                break
        else:
            raise TimeoutError()  # pragma: nocover
