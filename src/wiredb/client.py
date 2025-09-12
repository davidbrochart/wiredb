from __future__ import annotations

from importlib.metadata import entry_points

from pycrdt import Doc


class Client:
    def __init__(self, doc: Doc | None = None) -> None:
        self._doc = doc if doc is not None else Doc()

    @property
    def doc(self) -> Doc:
        return self._doc

    def connect(self, wire, *, id: str = "", **kwargs) -> Any:
        eps = entry_points(group="wires")
        Wire = eps[wire].load()
        wire = Wire(self._doc, id, **kwargs)
        return wire
