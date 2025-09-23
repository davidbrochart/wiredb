import pytest
from anyio import fail_after, sleep
from pycrdt import Text

from wiredb import bind, connect


pytestmark = pytest.mark.anyio

async def test_memory():
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
