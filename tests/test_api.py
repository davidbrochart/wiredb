import pytest

from wiredb import bind, connect


pytestmark = pytest.mark.anyio

async def test_server_not_found():
    with pytest.raises(RuntimeError) as excinfo:
        async with bind("foo"):
            pass

    assert str(excinfo.value) == 'No server found for "foo", did you forget to install "wire-foo"?'


async def test_client_not_found():
    with pytest.raises(RuntimeError) as excinfo:
        async with connect("foo"):
            pass

    assert str(excinfo.value) == 'No client found for "foo", did you forget to install "wire-foo"?'
