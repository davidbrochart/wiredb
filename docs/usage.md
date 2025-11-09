## Quickstart

WireDB has the notions of servers and clients. A server accepts connections from clients. Clients pass an `id` which is used to identify a "room" in the server. All clients in a room are kept in sync.

In WireDB, clients and servers can use a variety of "wires", or transport layers. For instance, here is how you would connect two clients together through a web server (using WebSockets):

```py
from anyio import run, sleep
from pycrdt import Text
from wire_websocket import AsyncWebSocketClient, AsyncWebSocketServer

async def main():
    async with AsyncWebSocketServer(host="localhost", port=8000) as server:
        async with (
            AsyncWebSocketClient(host="localhost", port=8000) as client0,
            AsyncWebSocketClient(host="localhost", port=8000) as client1,
        ):
            text0 = client0.doc.get("text", Text)
            text0 += "Hello, World!"
            await sleep(0.1)  # allow some time for synchronization
            text1 = client1.doc.get("text", Text)
            assert str(text1) == "Hello, World!"

run(main)
```

This example runs on the same machine and in the same process, but it would run just as well if the server and the clients were located on different machines on the Internet.

If you wanted to add persistence, you could connect a client to a file:

```py
from wire_file import AsyncFileClient

async def main():
    async with AsyncWebSocketServer(host="localhost", port=8000) as server:
        async with (
            AsyncWebSocketClient(host="localhost", port=8000) as client0,
            AsyncWebSocketClient(host="localhost", port=8000) as client1,
            AsyncFileClient(doc=client1.doc, path="/path/to/updates.y"),
        ):
            ...
```

But usually data is stored in the server, where clients are connected inside a room. Here is how you could connect these rooms to their corresponding files:

```py
from anyio import sleep_forever
from wiredb import Room

class MyRoom(Room):
    async def run(self, *args, **kwargs):
        await self.task_group.start(self.connect_to_file)
        await super().run(*args, **kwargs)

    async def connect_to_file(self, *, task_status) -> None:
        async with AsyncFileClient(doc=self.doc, path=f"/path/to/directory/{self.id}_updates.y"):
            task_status.started()
            await sleep_forever()

async def main():
    async with AsyncWebSocketServer(room_factory=MyRoom, host="localhost", port=8000) as server:
        async with (
            AsyncWebSocketClient(id="my_id", host="localhost", port=8000) as client0,
            AsyncWebSocketClient(id="my_id", host="localhost", port=8000) as client1,
        ):
            ...
```

The `id` of a `Room` is used to map to file paths. In the example above, the clients connect to the server
using `id="my_id"`, so the file name will be `my_id_updates.y`.
