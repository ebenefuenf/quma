import asyncio
from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from .. import exc
from . import util

pytestmark = pytest.mark.anyio


async def close_psycopg(raw):
    await raw.close()


async def close_asyncmy(raw):
    await raw.ensure_closed()


@pytest.fixture(
    params=[
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("asyncmy", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    pytest.importorskip(request.param)
    provider = import_module(f"quma.provider.{request.param}")
    if request.param == "psycopg":
        util.setup_pg_db()
        return SimpleNamespace(
            conn=provider.AsyncConnection,
            uri=util.pg_uri("psycopg"),
            url=urlparse(util.pg_uri("psycopg")),
            closed=lambda raw: raw.closed,
            autocommit=lambda raw: raw.autocommit,
            close=close_psycopg,
        )
    util.setup_mysql_db()
    uri = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
    return SimpleNamespace(
        conn=provider.AsyncConnection,
        uri=uri,
        url=urlparse(uri),
        closed=lambda raw: not raw.connected,
        autocommit=lambda raw: raw.get_autocommit(),
        close=close_asyncmy,
    )


async def test_get_and_put(driver):
    conn = driver.conn(driver.url)
    raw = await conn.get()
    assert not driver.autocommit(raw)
    assert not driver.closed(raw)
    await conn.put(raw)
    assert driver.closed(raw)


async def test_autocommit(driver):
    conn = driver.conn(driver.url)
    raw = await conn.get(autocommit=True)
    assert driver.autocommit(raw)
    await conn.put(raw)


async def test_connection_error(driver):
    conn = driver.conn(urlparse(driver.uri + "_wrong"))
    with pytest.raises(exc.ConnectionError):
        await conn.get()


async def test_persistent_opens_on_first_use(driver):
    conn = driver.conn(driver.url, persist=True)
    assert conn.conn is None
    raw = await conn.get()
    assert await conn.get() is raw
    await conn.put(raw)
    assert not driver.closed(raw)
    await conn.close()
    assert driver.closed(raw)
    assert conn.conn is None
    await conn.close()


async def test_persistent_opens_once_for_concurrent_tasks(driver):
    conn = driver.conn(driver.url, persist=True)
    raws = await asyncio.gather(*(conn.get() for _ in range(5)))
    assert len({id(raw) for raw in raws}) == 1
    await conn.close()


async def test_close_waits_for_persistent_connection_being_opened(driver):
    conn = driver.conn(driver.url, persist=True)
    getting = asyncio.create_task(conn.get())
    await asyncio.sleep(0)
    await conn.close()
    raw = await getting
    assert driver.closed(raw)
    with pytest.raises(exc.APIError, match="closed"):
        await conn.get()


async def test_open(driver):
    conn = driver.conn(driver.url, persist=True)
    await conn.open()
    assert conn.conn is not None
    await conn.close()
    plain = driver.conn(driver.url)
    await plain.open()
    assert plain.conn is None


async def test_pessimistic_replaces_closed(driver):
    conn = driver.conn(driver.url, persist=True, pessimistic=True)
    raw = await conn.get()
    await conn.put(raw)
    await driver.close(raw)
    replaced = await conn.get()
    assert replaced is not raw
    assert not driver.closed(replaced)
    await conn.close()


async def test_broken_persistent_reconnects(driver):
    conn = driver.conn(driver.url, persist=True)
    raw = await conn.get()
    await driver.close(raw)
    await conn.put(raw)
    assert conn.conn is None
    replaced = await conn.get()
    assert not driver.closed(replaced)
    await conn.close()


async def test_cancelled_reset_discards_connection(driver):
    conn = driver.conn(driver.url, persist=True)
    raw = await conn.get()

    async def cancelled():
        raise asyncio.CancelledError

    raw.rollback = cancelled
    with pytest.raises(asyncio.CancelledError):
        await conn.put(raw)
    assert driver.closed(raw)
    assert conn.conn is None


async def test_fetch_after_statement_without_result(driver):
    conn = driver.conn(driver.url)
    raw = await conn.get()
    cursor = conn.cursor(raw)
    await cursor.execute("CREATE TEMPORARY TABLE no_result (id integer)")
    assert await conn.get_cursor_attr(cursor, "fetchall")() == ()
    await cursor.execute("SELECT 1 AS one")
    rows = await conn.get_cursor_attr(cursor, "fetchall")()
    assert rows[0][0] == 1
    await conn.put(raw)


async def test_mogrify(driver):
    conn = driver.conn(driver.url)
    raw = await conn.get()
    cursor = conn.cursor(raw)
    await cursor.execute("SELECT 1 AS one")
    sql = conn.mogrify(cursor, "SELECT %(name)s", {"name": "quma"})
    assert sql == "SELECT 'quma'"
    assert (await cursor.fetchall())[0][0] == 1
    await conn.put(raw)


def pool(driver, **kwargs):
    from ..aio.pool import AsyncPool

    return AsyncPool(driver.conn, driver.url, **kwargs)


async def test_pool_reuses_connections(driver):
    p = pool(driver, size=1)
    raw = await p.get()
    assert p.checkedout == 1
    await p.put(raw)
    assert p.checkedout == 0
    assert p.checkedin == 1
    assert await p.get() is raw
    await p.put(raw)
    await p.close()
    assert driver.closed(raw)


async def test_pool_closes_surplus_connections(driver):
    p = pool(driver, size=1, overflow=2)
    raws = [await p.get() for _ in range(3)]
    assert p.overflow == 2
    for raw in raws:
        await p.put(raw)
    assert p.checkedin == 1
    assert p.overflow == 0
    assert [driver.closed(raw) for raw in raws] == [False, True, True]
    assert p.status() == (
        "Pool size: 1 Connections in pool: 1 Current Overflow: 0 "
        "Current Checked out connections: 0"
    )
    await p.close()


async def test_pool_timeout(driver):
    p = pool(driver, size=1, overflow=1, timeout=0.05)
    raws = [await p.get(), await p.get()]
    with pytest.raises(exc.TimeoutError):
        await p.get()
    for raw in raws:
        await p.put(raw)
    await p.close()


async def test_pool_unlimited_overflow(driver):
    p = pool(driver, size=1, overflow=-1)
    raws = [await p.get() for _ in range(4)]
    assert p.checkedout == 4
    for raw in raws:
        await p.put(raw)
    assert p.checkedout == 0
    await p.close()


async def test_pool_waiter_gets_returned_connection(driver):
    p = pool(driver, size=1, overflow=0)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.01)
    assert not waiter.done()
    await p.put(raw)
    assert await waiter is raw
    await p.put(raw)
    await p.close()


async def test_pool_waiter_wakes_when_broken_connection_is_discarded(driver):
    p = pool(driver, size=1, overflow=0)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.01)
    await driver.close(raw)
    await p.put(raw)
    replaced = await waiter
    assert replaced is not raw
    assert p.checkedout == 1
    await p.put(replaced)
    await p.close()


async def test_pool_cancelled_waiter_loses_no_slot(driver):
    p = pool(driver, size=1, overflow=0)
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


async def test_pool_cancelled_reset_frees_slot(driver):
    p = pool(driver, size=1, overflow=0)
    raw = await p.get()

    async def cancelled():
        raise asyncio.CancelledError

    raw.rollback = cancelled
    with pytest.raises(asyncio.CancelledError):
        await p.put(raw)
    assert driver.closed(raw)
    assert p.checkedout == 0
    async with asyncio.timeout(1):
        replaced = await p.get()
    await p.put(replaced)
    await p.close()


async def test_pool_cancelled_connect_frees_slot(driver, monkeypatch):
    p = pool(driver, size=1, overflow=0)

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


async def test_pool_pessimistic_replaces_closed(driver):
    p = pool(driver, size=1, overflow=0, pessimistic=True)
    raw = await p.get()
    await p.put(raw)
    await driver.close(raw)
    replaced = await p.get()
    assert replaced is not raw
    assert not driver.closed(replaced)
    assert p.checkedout == 1
    await p.put(replaced)
    await p.close()


async def test_pool_discards_connections_returned_after_close(driver):
    p = pool(driver, size=1)
    raw = await p.get()
    await p.close()
    await p.put(raw)
    assert driver.closed(raw)
    assert p.checkedin == 0


def test_pool_refuses_persistent_connections(driver):
    with pytest.raises(ValueError):
        pool(driver, persist=True)
