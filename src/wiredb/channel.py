from abc import ABC, abstractmethod


class Channel(ABC):
    """A transport-agnostic stream used to synchronize a document.
    An example of a channel is a WebSocket.

    Messages can be received by calling `receive()`, which takes an optional
    timeout:
    ```py
    message = channel.receive()  # will block until a message is received
    message = channel.receive(0)  # will return a message is one is available, or raise TimeoutError
    ```
    Sending messages is done with `send()`:
    ```py
    channel.send(message)
    ```
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """The channel ID."""
        ...  # pragma: nocover

    @abstractmethod
    def send(self, message: bytes) -> None:
        """Sends a message.

        Args:
            message: The message to send.
        """
        ...  # pragma: nocover

    @abstractmethod
    def receive(self, timeout: float | None = None) -> bytes:
        """Receives a message.

        Args:
            timeout: The time to wait until a message is received.

        Returns:
            The received message.

        Raises:
            TimeoutError: A message was not received before `timeout`.
        """
        ...  # pragma: nocover


class AsyncChannel(ABC):
    """A transport-agnostic asynchronous stream used to synchronize a document.
    An example of a channel is a WebSocket.

    Messages can be received through the channel using an async iterator,
    until the connection is closed:
    ```py
    async for message in channel:
        ...
    ```
    Or directly by calling `receive()`:
    ```py
    message = await channel.receive()
    ```
    Sending messages is done with `send()`:
    ```py
    await channel.send(message)
    ```
    """

    @property
    @abstractmethod
    def id(self) -> str:
        """The channel ID."""
        ...  # pragma: nocover

    def __aiter__(self) -> "AsyncChannel":
        return self

    async def __anext__(self) -> bytes:
        return await self.receive()  # pragma: nocover

    @abstractmethod
    async def send(self, message: bytes) -> None:
        """Sends a message.

        Args:
            message: The message to send.
        """
        ...  # pragma: nocover

    @abstractmethod
    async def receive(self) -> bytes:
        """Receives a message.

        Returns:
            The received message.
        """
        ...  # pragma: nocover
