import time
from multiprocessing import Process

from anyio import run, sleep_forever
from wiredb import bind

import pytest
import requests  # type: ignore[import-untyped]


def server(host: str, port: int):  # pragma: nocover
    async def main():
        async with bind("websocket", host=host, port=port):
            await sleep_forever()

    run(main)


@pytest.fixture()
def websocket_server(free_tcp_port: int):
    host = "localhost"
    p = Process(target=server, args=(host, free_tcp_port,))
    p.start()
    url = f"http://{host}:{free_tcp_port}"
    while True:
        try:
            requests.get(url)
        except requests.exceptions.ConnectionError:
            time.sleep(0.1)
        else:
            break
    yield host, free_tcp_port
    p.terminate()
    while True:
        time.sleep(0.1)
        if not p.is_alive():
            break
