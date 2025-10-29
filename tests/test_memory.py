import pytest
from anyio import fail_after, sleep, wait_all_tasks_blocked
from pycrdt import Text

from wiredb import bind, connect


pytestmark = pytest.mark.anyio

async def test_memory() -> None:
    async with bind("memory") as server:
        async with (
            connect("memory", server=server) as client0,
            connect("memory", server=server) as client1,
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
    async with bind("memory") as server:
        async with (
            connect("memory", server=server) as client0,
            connect("memory", auto_update=False, server=server) as client1,
        ):
            text0 = client0.doc.get("text", type=Text)
            text1 = client1.doc.get("text", type=Text)
            text0 += "Hello"
            text0 += ", "
            await wait_all_tasks_blocked()
            assert str(text1) == ""
            client1.pull()
            await wait_all_tasks_blocked()
            assert str(text1) == "Hello, "
            text1 += "World!"
            await wait_all_tasks_blocked()
            assert str(text0) == "Hello, "
            client1.push()
            await wait_all_tasks_blocked()
            assert str(text0) == "Hello, World!"
