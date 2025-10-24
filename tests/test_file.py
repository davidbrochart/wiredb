import re
from pathlib import Path
from typing import cast

import pytest

from anyio import sleep, wait_all_tasks_blocked
from pycrdt import Doc, Text

from wiredb import connect
from wire_file.client_wire import ClientWire


pytestmark = pytest.mark.anyio

async def test_file_without_write_delay(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    doc0: Doc = Doc()
    async with connect("file", doc=doc0, path=update_path, write_delay=0):
        text0 = doc0.get("text", type=Text)
        text0 += "Hello"
        await wait_all_tasks_blocked()
    assert b"Hello" in update_path.read_bytes()

    doc1: Doc = Doc()
    async with connect("file", doc=doc1, path=update_path, write_delay=0):
        pass
    text1 = doc1.get("text", type=Text)
    assert str(text1) == "Hello"


async def test_file_with_write_delay(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    doc: Doc = Doc()
    async with connect("file", doc=doc, path=update_path, write_delay=0.1) as client:
        client = cast(ClientWire, client)
        text = doc.get("text", type=Text)
        for i in range(20):
            text += "."
            await sleep(0.01)
        header = client.version.encode() + bytes([0])
        assert update_path.read_bytes() == header
        await sleep(0.2)
        data = update_path.read_bytes()
        assert data.startswith(header)
        assert len(data) > len(header)


async def test_file_wrong_version(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    update_path.write_bytes(b"0.0.0" + bytes([0]))

    with pytest.raises(RuntimeError, match=re.escape('File version mismatch (got "0.0.0", expected "0.0.1")')):
        async with connect("file", path=update_path):
            pass  # pragma: nocover


async def test_squash(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    async with connect("file", path=update_path) as client:
        text = client.doc.get("text", type=Text)
        text += "Hello"
        await wait_all_tasks_blocked()
        text += ", "
        await wait_all_tasks_blocked()
        text += "World!"
        await wait_all_tasks_blocked()
    data = update_path.read_bytes()
    assert b"Hello" in data
    assert b", " in data
    assert b"World!" in data
    assert b"Hello, World!" not in data
    size0 = len(data)

    async with connect("file", path=update_path, squash=False) as client:
        pass
    data = update_path.read_bytes()
    size1 = len(data)
    assert size1 == size0
    assert b"Hello" in data
    assert b", " in data
    assert b"World!" in data
    assert b"Hello, World!" not in data

    async with connect("file", path=update_path, squash=True) as client:
        pass
    data = update_path.read_bytes()
    assert b"Hello, World!" in data

    async with connect("file", path=update_path, squash=True) as client:
        text = client.doc.get("text", type=Text)
        text += " Goodbye."
        await wait_all_tasks_blocked()
    data = update_path.read_bytes()
    assert b"Hello, World!" in data
    assert b" Goodbye." in data
    assert b"Hello, World! Goodbye." not in data


@pytest.mark.skip(reason="Updates from different docs are not squashed")
async def test_not_squash(tmp_path: Path) -> None:  # pragma: nocover
    update_path = tmp_path / "updates.y"
    async with connect("file", path=update_path) as client:
        text = client.doc.get("text", type=Text)
        text += "Hello"
        await wait_all_tasks_blocked()
    size0 = len(update_path.read_bytes())

    async with connect("file", path=update_path) as client:
        text = client.doc.get("text", type=Text)
        text += ", "
        await wait_all_tasks_blocked()
    size1 = len(update_path.read_bytes())
    assert size1 > size0

    async with connect("file", path=update_path) as client:
        text = client.doc.get("text", type=Text)
        text += "World!"
        await wait_all_tasks_blocked()
    size2 = len(update_path.read_bytes())
    assert size2 > size1

    async with connect("file", path=update_path, squash=False) as client:
        pass
    data = update_path.read_bytes()
    assert b"Hello" in data
    assert b", " in data
    assert b"World!" in data
    assert b"Hello, World!" not in data

    async with connect("file", path=update_path, squash=True) as client:
        pass
    data = update_path.read_bytes()
    assert b"Hello, World!" in data


async def test_reconnect_after_update(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    doc: Doc = Doc()
    async with connect("file", doc=doc, path=update_path) as client:
        text = doc.get("text", type=Text)
        text += "Hello"
        await wait_all_tasks_blocked()
        text += ", "
        await wait_all_tasks_blocked()
        text += "World!"
        await wait_all_tasks_blocked()
    size0 = len(update_path.read_bytes())

    async with connect("file", path=update_path, squash=False) as client:
        client_text = client.doc.get("text", type=Text)
    assert str(client_text) == "Hello, World!"
    size1 = len(update_path.read_bytes())
    assert size1 == size0

    async with connect("file", path=update_path, squash=True) as client:
        client_text = client.doc.get("text", type=Text)
    assert str(client_text) == "Hello, World!"
    size2 = len(update_path.read_bytes())
    assert size2 < size0

    text += " Goodbye."

    async with connect("file", doc=doc, path=update_path) as client:
        pass
    size3 = len(update_path.read_bytes())
    assert size3 > size2

    async with connect("file", path=update_path) as client:
        client_text = client.doc.get("text", type=Text)
    assert str(client_text) == "Hello, World! Goodbye."
    size4 = len(update_path.read_bytes())
    assert size4 == size3
