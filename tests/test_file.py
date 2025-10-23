import re
from pathlib import Path

import pytest

from anyio import sleep
from pycrdt import Doc, Text

from wiredb import connect


pytestmark = pytest.mark.anyio

async def test_file_without_write_delay(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    doc0: Doc = Doc()
    async with connect("file", doc=doc0, path=update_path, write_delay=0):
        text0 = doc0.get("text", type=Text)
        text0 += "Hello"
        await sleep(0.1)
        assert b"Hello" in update_path.read_bytes()

    doc1: Doc = Doc()
    async with connect("file", doc=doc1, path=update_path, write_delay=0):
        text1 = doc1.get("text", type=Text)
        assert str(text1) == "Hello"


async def test_file_with_write_delay(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    doc: Doc = Doc()
    version = "0.0.0"
    async with connect("file", doc=doc, path=update_path, write_delay=0.1, version=version):
        text = doc.get("text", type=Text)
        for i in range(20):
            text += "."
            await sleep(0.01)
        header = version.encode() + bytes([0])
        assert update_path.read_bytes() == header
        await sleep(0.2)
        data = update_path.read_bytes()
        assert data.startswith(header)
        assert len(data) > len(header)


async def test_file_wrong_version(tmp_path: Path) -> None:
    update_path = tmp_path / "updates.y"
    async with connect("file", path=update_path, version="0.0.0"):
        pass

    with pytest.raises(RuntimeError, match=re.escape('File version mismatch (got "0.0.0", expected "0.0.1")')):
        async with connect("file", path=update_path, version="0.0.1"):
            pass  # pragma: nocover
