import pytest
from anyio import fail_after, sleep
from pycrdt import Text

from wiredb import bind, connect


pytestmark = pytest.mark.anyio

async def test_pipe(anyio_backend):
    if anyio_backend == "trio":
        pytest.skip("Hangs on Trio")

    async with bind("pipe") as server:
        connection0 = await server.connect("")
        connection1 = await server.connect("")
        async with (
            connect("pipe", connection=connection0) as client0,
            connect("pipe", connection=connection1) as client1,
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
