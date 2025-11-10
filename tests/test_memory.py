import pytest
from anyio import fail_after, sleep, wait_all_tasks_blocked
from pycrdt import Text

from wire_memory import AsyncMemoryServer, AsyncMemoryClient


pytestmark = pytest.mark.anyio


async def test_memory() -> None:
    async with AsyncMemoryServer() as server:
        async with (
            AsyncMemoryClient(server=server) as client0,
            AsyncMemoryClient(server=server) as client1,
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


async def test_push_pull() -> None:
    async with AsyncMemoryServer() as server:
        async with (
            AsyncMemoryClient(server=server) as client0,
            AsyncMemoryClient(
                auto_push=False, auto_pull=False, server=server
            ) as client1,
        ):
            text0 = client0.doc.get("text", type=Text)
            text1 = client1.doc.get("text", type=Text)
            text0 += "Hello"
            text0 += ", "
            await wait_all_tasks_blocked()
            assert str(text1) == ""
            assert not client1.synchronized.is_set()
            client1.pull()
            await client1.synchronized.wait()
            assert str(text1) == "Hello, "
            text1 += "World!"
            await wait_all_tasks_blocked()
            assert str(text0) == "Hello, "
            client1.push()
            await wait_all_tasks_blocked()
            assert str(text0) == "Hello, World!"
