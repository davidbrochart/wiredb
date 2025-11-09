import time
from multiprocessing import Process

from anyio import run, sleep_forever
from wire_websocket import AsyncWebSocketServer

import pytest
import httpx


def run_server(host: str, port: int):  # pragma: nocover
    async def main():
        async with AsyncWebSocketServer(host=host, port=port):
            await sleep_forever()

    run(main)


@pytest.fixture()
def websocket_server(free_tcp_port: int):
    host = "localhost"
    p = Process(target=run_server, args=(host, free_tcp_port))
    p.start()
    url = f"http://{host}:{free_tcp_port}"
    while True:
        try:
            httpx.get(url)
        except httpx.ConnectError:
            time.sleep(0.1)
        else:
            break
    yield host, free_tcp_port
    p.terminate()
    while True:
        time.sleep(0.1)
        if not p.is_alive():
            break
