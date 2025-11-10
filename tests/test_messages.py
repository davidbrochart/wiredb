from contextlib import AsyncExitStack
from typing import cast

import pytest
from anyio import wait_all_tasks_blocked
from pycrdt import Text

from wire_memory import AsyncMemoryClient, AsyncMemoryServer, Memory


pytestmark = pytest.mark.anyio


@pytest.mark.parametrize("client_nb", [1, 2, 5, 10])
async def test_messages(client_nb: int) -> None:
    async with AsyncMemoryServer() as server:
        async with AsyncExitStack() as stack:
            clients = [
                await stack.enter_async_context(AsyncMemoryClient(server=server))
                for i in range(client_nb)
            ]
            for client in clients:
                text = client.doc.get("text", type=Text)
                text += "Hello"
            await wait_all_tasks_blocked()
            for client in clients:
                channel = cast(Memory, client.channel)
                assert channel.send_nb == client_nb + 2
                assert channel.receive_nb == client_nb + 2
