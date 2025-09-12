import asyncio
from anycorn import Config, serve
from pycrdt.websocket import ASGIServer, WebsocketServer


websocket_server = WebsocketServer()
app = ASGIServer(websocket_server)

async def main():
    websocket_server = WebsocketServer()
    app = ASGIServer(websocket_server)
    config = Config()
    config.bind = ["localhost:1234"]
    async with websocket_server:
        await serve(app, config, mode="asgi")

asyncio.run(main())
