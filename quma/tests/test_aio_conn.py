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


async def test_close_waits_for_persistent_connection_being_opened():
    conn = AsyncConnection(URL, persist=True)
    getting = asyncio.create_task(conn.get())
    await asyncio.sleep(0)
    await conn.close()
    raw = await getting
    assert raw.closed
    with pytest.raises(exc.APIError, match="closed"):
        await conn.get()


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


def pool(**kwargs):
    from ..aio.pool import AsyncPool

    return AsyncPool(AsyncConnection, URL, **kwargs)


async def test_pool_reuses_connections():
    p = pool(size=1)
    raw = await p.get()
    assert p.checkedout == 1
    await p.put(raw)
    assert p.checkedout == 0
    assert p.checkedin == 1
    assert await p.get() is raw
    await p.put(raw)
    await p.close()
    assert raw.closed


async def test_pool_closes_surplus_connections():
    p = pool(size=1, overflow=2)
    raws = [await p.get() for _ in range(3)]
    assert p.overflow == 2
    for raw in raws:
        await p.put(raw)
    assert p.checkedin == 1
    assert p.overflow == 0
    assert [raw.closed for raw in raws] == [False, True, True]
    assert p.status() == (
        "Pool size: 1 Connections in pool: 1 Current Overflow: 0 "
        "Current Checked out connections: 0"
    )
    await p.close()


async def test_pool_timeout():
    p = pool(size=1, overflow=1, timeout=0.05)
    raws = [await p.get(), await p.get()]
    with pytest.raises(exc.TimeoutError):
        await p.get()
    for raw in raws:
        await p.put(raw)
    await p.close()


async def test_pool_unlimited_overflow():
    p = pool(size=1, overflow=-1)
    raws = [await p.get() for _ in range(4)]
    assert p.checkedout == 4
    for raw in raws:
        await p.put(raw)
    assert p.checkedout == 0
    await p.close()


async def test_pool_waiter_gets_returned_connection():
    p = pool(size=1, overflow=0)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    await p.put(raw)
    assert await waiter is raw
    await p.put(raw)
    await p.close()


async def test_pool_waiter_wakes_when_broken_connection_is_discarded():
    p = pool(size=1, overflow=0)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.01)
    await raw.close()
    await p.put(raw)
    replaced = await waiter
    assert replaced is not raw
    assert p.checkedout == 1
    await p.put(replaced)
    await p.close()


async def test_pool_cancelled_waiter_loses_no_slot():
    p = pool(size=1, overflow=0)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.01)
    waiter.cancel()
    with pytest.raises(asyncio.CancelledError):
        await waiter
    await p.put(raw)
    async with asyncio.timeout(1):
        assert await p.get() is raw
    await p.put(raw)
    await p.close()


async def test_pool_cancelled_reset_frees_slot():
    p = pool(size=1, overflow=0)
    raw = await p.get()

    async def cancelled():
        raise asyncio.CancelledError

    raw.rollback = cancelled
    with pytest.raises(asyncio.CancelledError):
        await p.put(raw)
    assert raw.closed
    assert p.checkedout == 0
    async with asyncio.timeout(1):
        replaced = await p.get()
    await p.put(replaced)
    await p.close()


async def test_pool_cancelled_connect_frees_slot(monkeypatch):
    p = pool(size=1, overflow=0)

    async def cancelled(**kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(p._conn, "create_conn", cancelled)
    with pytest.raises(asyncio.CancelledError):
        await p.get()
    monkeypatch.undo()
    assert p.checkedout == 0
    async with asyncio.timeout(1):
        raw = await p.get()
    await p.put(raw)
    await p.close()


async def test_pool_pessimistic_replaces_closed():
    p = pool(size=1, overflow=0, pessimistic=True)
    raw = await p.get()
    await p.put(raw)
    await raw.close()
    replaced = await p.get()
    assert replaced is not raw
    assert not replaced.closed
    assert p.checkedout == 1
    await p.put(replaced)
    await p.close()


async def test_pool_discards_connections_returned_after_close():
    p = pool(size=1)
    raw = await p.get()
    await p.close()
    await p.put(raw)
    assert raw.closed
    assert p.checkedin == 0


def test_pool_refuses_persistent_connections():
    with pytest.raises(ValueError):
        pool(persist=True)
