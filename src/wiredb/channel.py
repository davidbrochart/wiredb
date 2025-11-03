from abc import ABC, abstractmethod


class Channel(ABC):
    """A transport-agnostic stream used to synchronize a document.
    An example of a channel is a WebSocket.

    Messages can be received through the channel using an async iterator,
    until the connection is closed:
    ```py
    async for message in channel:
        ...
    ```
    Or directly by calling `arecv()`:
    ```py
    message = await channel.arecv()
    ```
    Sending messages is done with `asend()`:
    ```py
    await channel.asend(message)
    ```
    """

    @property
    @abstractmethod
    def path(self) -> str:
        """The channel path."""
        ...  # pragma: nocover

    def __iter__(self) -> "Channel":
        return self  # pragma: nocover

    def __aiter__(self) -> "Channel":
        return self

    def __next__(self) -> bytes:
        return self.recv()  # pragma: nocover

    async def __anext__(self) -> bytes:
        return await self.arecv()  # pragma: nocover

    def send(self, message: bytes) -> None:
        """Send a message.

        Args:
            message: The message to send.
        """
        raise NotImplementedError()  # pragma: nocover

    def recv(self) -> bytes:
        """Receive a message.

        Returns:
            The received message.
        """
        raise NotImplementedError()  # pragma: nocover

    async def asend(self, message: bytes) -> None:
        """Send a message.

        Args:
            message: The message to send.
        """
        raise NotImplementedError()  # pragma: nocover

    async def arecv(self) -> bytes:
        """Receive a message.

        Returns:
            The received message.
        """
        raise NotImplementedError()  # pragma: nocover
