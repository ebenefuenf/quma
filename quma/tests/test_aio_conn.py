import asyncio
from urllib.parse import urlparse

import pytest

from .. import exc
from . import util

pytest.importorskip("psycopg")

from ..provider.psycopg import AsyncConnection  # noqa: E402

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]

URL = urlparse(util.pg_uri("psycopg"))


def setup_function(function):
    util.setup_pg_db()


async def test_get_and_put():
    conn = AsyncConnection(URL)
    raw = await conn.get()
    assert not raw.autocommit
    assert not raw.closed
    await conn.put(raw)
    assert raw.closed


async def test_autocommit():
    conn = AsyncConnection(URL)
    raw = await conn.get(autocommit=True)
    assert raw.autocommit
    await conn.put(raw)


async def test_connection_error():
    conn = AsyncConnection(urlparse(util.pg_uri("psycopg") + "_wrong"))
    with pytest.raises(exc.ConnectionError):
        await conn.get()


async def test_persistent_opens_on_first_use():
    conn = AsyncConnection(URL, persist=True)
    assert conn.conn is None
    raw = await conn.get()
    assert await conn.get() is raw
    await conn.put(raw)
    assert not raw.closed
    await conn.close()
    assert raw.closed
    assert conn.conn is None
    await conn.close()


async def test_persistent_opens_once_for_concurrent_tasks():
    conn = AsyncConnection(URL, persist=True)
    raws = await asyncio.gather(*(conn.get() for _ in range(5)))
    assert len({id(raw) for raw in raws}) == 1
    await conn.close()


async def test_open():
    conn = AsyncConnection(URL, persist=True)
    await conn.open()
    assert conn.conn is not None
    await conn.close()
    plain = AsyncConnection(URL)
    await plain.open()
    assert plain.conn is None


async def test_pessimistic_replaces_closed():
    conn = AsyncConnection(URL, persist=True, pessimistic=True)
    raw = await conn.get()
    await conn.put(raw)
    await raw.close()
    replaced = await conn.get()
    assert replaced is not raw
    assert not replaced.closed
    await conn.close()


async def test_broken_persistent_reconnects():
    conn = AsyncConnection(URL, persist=True)
    raw = await conn.get()
    await raw.close()
    await conn.put(raw)
    assert conn.conn is None
    replaced = await conn.get()
    assert not replaced.closed
    await conn.close()


async def test_cancelled_reset_discards_connection():
    conn = AsyncConnection(URL, persist=True)
    raw = await conn.get()

    async def cancelled():
        raise asyncio.CancelledError

    raw.rollback = cancelled
    with pytest.raises(asyncio.CancelledError):
        await conn.put(raw)
    assert raw.closed
    assert conn.conn is None


async def test_fetch_after_statement_without_result():
    conn = AsyncConnection(URL)
    raw = await conn.get()
    cursor = conn.cursor(raw)
    await cursor.execute("CREATE TEMP TABLE no_result (id integer)")
    assert await conn.get_cursor_attr(cursor, "fetchall")() == ()
    await cursor.execute("SELECT 1 AS one")
    rows = await conn.get_cursor_attr(cursor, "fetchall")()
    assert rows[0]["one"] == 1
    await conn.put(raw)


async def test_mogrify():
    conn = AsyncConnection(URL)
    raw = await conn.get()
    cursor = conn.cursor(raw)
    await cursor.execute("SELECT 1 AS one")
    sql = conn.mogrify(cursor, "SELECT %(name)s", {"name": "quma"})
    assert sql == "SELECT 'quma'"
    assert (await cursor.fetchall())[0]["one"] == 1
    await conn.put(raw)
