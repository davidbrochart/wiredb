import pytest
from anyio import TASK_STATUS_IGNORED, create_task_group, fail_after, sleep, sleep_forever
from anyio.abc import TaskStatus
from pycrdt import Doc, Text

from wiredb import Room, RoomManager, bind, connect


pytestmark = pytest.mark.anyio

async def test_websocket(free_tcp_port: int) -> None:
    async with bind("websocket", host="localhost", port=free_tcp_port):
        async with (
            connect("websocket", host="http://localhost", port=free_tcp_port) as client0,
            connect("websocket", host="http://localhost", port=free_tcp_port) as client1,
        ):
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


async def test_multiple_servers(free_tcp_port_factory):
    port0 = free_tcp_port_factory()
    port1 = free_tcp_port_factory()
    port2 = free_tcp_port_factory()

    class MyRoom(Room):
        async def run(self, *args, **kwargs) -> None:
            await self.task_group.start(self._connect_to_server)
            await super().run(*args, **kwargs)

        async def _connect_to_server(self, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
            async with connect("websocket", id=self.id, doc=self.doc, host="http://localhost", port=port0):
                task_status.started()
                await sleep_forever()

    async def run_server(port: int, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED):
        server = bind("websocket", host="localhost", port=port)
        if port != port0:
            server.room_manager = RoomManager(room_factory=MyRoom)
        async with server:
            task_status.started()
            await sleep_forever()

    async def run_client(doc, port, message):
        async with connect("websocket", doc=doc, host="http://localhost", port=port):
            text = doc.get("text", type=Text)
            text += message
            await sleep_forever()

    async with create_task_group() as tg:
        await tg.start(run_server, port0)
        await tg.start(run_server, port1)
        await tg.start(run_server, port2)
        doc1 = Doc()
        doc2 = Doc()
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
