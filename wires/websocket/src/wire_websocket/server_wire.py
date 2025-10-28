from __future__ import annotations

from collections.abc import Callable
from contextlib import AsyncExitStack
from types import TracebackType

from anyio import Event, create_task_group
from anycorn import Config, serve
from wiredb import Channel, Room, ServerWire as _ServerWire

from .asgi_server import ASGIServer


class ServerWire(_ServerWire):
    def __init__(self, room_factory: Callable[[str], Room] = Room, *, host: str, port: int) -> None:
        super().__init__(room_factory=room_factory)
        self._host = host
        self._port = port
        self._app = ASGIServer(self._serve)
        self._config = Config()
        self._config.bind = [f"{host}:{port}"]
        self._shutdown_event = Event()

    async def __aenter__(self) -> ServerWire:
        async with AsyncExitStack() as exit_stack:
            self._task_group = await exit_stack.enter_async_context(create_task_group())
            await exit_stack.enter_async_context(self.room_manager)
            self._task_group.start_soon(lambda: serve(self._app, self._config, shutdown_trigger=self._shutdown_event.wait, mode="asgi"))  # type: ignore[arg-type]
            self._exit_stack = exit_stack.pop_all()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        self._shutdown_event.set()
        return await self._exit_stack.__aexit__(exc_type, exc_val, exc_tb)

    async def _serve(self, websocket: Channel) -> None:
        room = await self.room_manager.get_room(websocket.path)
        await room.serve(websocket)
