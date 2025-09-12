import pytest
from anyio import Event, create_task_group, fail_after, sleep
from anycorn import Config, serve
from pycrdt import Text
from pycrdt.websocket import ASGIServer, WebsocketServer

from wiredb import Client


pytestmark = pytest.mark.anyio

async def test_websocket_client(free_tcp_port):
    websocket_server = WebsocketServer()
    app = ASGIServer(websocket_server)
    config = Config()
    config.bind = [f"localhost:{free_tcp_port}"]
    shutdown_event = Event()
    async with create_task_group() as tg, websocket_server:
        tg.start_soon(lambda: serve(app, config, shutdown_trigger=shutdown_event.wait, mode="asgi"))
        client0 = Client()
        client1 = Client()
        async with (
            client0.connect("websocket", host="http://localhost", port=free_tcp_port),
            client1.connect("websocket", host="http://localhost", port=free_tcp_port),
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
                        shutdown_event.set()
                        break
