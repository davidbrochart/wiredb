from contextlib import AsyncExitStack

import pytest
from anyio import sleep
from pycrdt import Text

from wiredb import bind, connect


pytestmark = pytest.mark.anyio

@pytest.mark.parametrize("client_nb", [1, 2, 5, 10])
async def test_messages(client_nb):
    async with bind("memory") as server:
        async with AsyncExitStack() as stack:
            clients = [await stack.enter_async_context(connect("memory", server=server)) for i in range(client_nb)]
            for client in clients:
                text = client.doc.get("text", type=Text)
                text += "Hello"
            await sleep(0.1)
            for client in clients:
                assert client.channel.send_nb == client_nb + 2
                assert client.channel.receive_nb == client_nb + 2
