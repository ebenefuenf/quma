import asyncio
from importlib import import_module
from types import SimpleNamespace
from urllib.parse import urlparse

import pytest

from .. import AsyncDatabase, exc
from ..aio import pool as aio_pool
from . import util

pytestmark = pytest.mark.anyio


async def close_psycopg(raw):
    await raw.close()


async def close_asyncmy(raw):
    await raw.ensure_closed()


@pytest.fixture(
    params=[
        "aiosqlite",
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("asyncmy", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    pytest.importorskip(request.param)
    provider = import_module(f"quma.provider.{request.param}")
    if request.param == "aiosqlite":
        uri = f"aiosqlite:///{util.SQLITE_FILE}"
        return SimpleNamespace(
            conn=provider.AsyncConnection,
            uri=uri,
            url=urlparse(uri),
            closed=lambda raw: raw._connection is None,
            autocommit=lambda raw: raw.isolation_level is None,
            close=close_psycopg,
        )
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
    wrong = (
        "aiosqlite:////nonexistent/directory/quma.sqlite"
        if driver.uri.startswith("aiosqlite")
        else driver.uri + "_wrong"
    )
    conn = driver.conn(urlparse(wrong))
    with pytest.raises(exc.ConnectionError):
        await conn.get()


async def test_persistent_autocommit_ends_with_the_checkout(driver):
    conn = driver.conn(driver.url, persist=True)
    raw = await conn.get(autocommit=True)
    assert driver.autocommit(raw)
    await conn.put(raw)
    assert not driver.autocommit(raw)
    assert await conn.get() is raw
    assert not driver.autocommit(raw)
    await conn.put(raw)
    await conn.close()


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
    assert await conn.get_cursor_attr(cursor, "fetchmany")(2) == ()
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
    # SQLite binds on the server, so there is nothing to show but the SQL.
    assert sql == (
        "SELECT %(name)s"
        if driver.uri.startswith("aiosqlite")
        else "SELECT 'quma'"
    )
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
    assert p.checkedin == 0
    assert p.checkedout == 0


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


async def test_pool_timeout_defaults_to_30_seconds(driver, monkeypatch):
    assert aio_pool.DEFAULT_TIMEOUT == 30
    monkeypatch.setattr(aio_pool, "DEFAULT_TIMEOUT", 0.01)
    p = pool(driver, size=1, overflow=0)
    raw = await p.get()
    with pytest.raises(exc.TimeoutError):
        await p.get()
    await p.put(raw)
    await p.close()


async def test_pool_timeout_none_waits_for_a_connection(driver, monkeypatch):
    monkeypatch.setattr(aio_pool, "DEFAULT_TIMEOUT", 0.01)
    p = pool(driver, size=1, overflow=0, timeout=None)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0.05)
    assert not waiter.done()
    await p.put(raw)
    assert await waiter is raw
    await p.put(raw)
    await p.close()


async def test_pool_new_request_queues_behind_waiters(driver):
    p = pool(driver, size=1, overflow=0)
    raw = await p.get()
    first = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    await p.put(raw)
    second = asyncio.create_task(p.get())
    assert await first is raw
    await asyncio.sleep(0.01)
    assert not second.done()
    await p.put(raw)
    assert await second is raw
    await p.put(raw)
    await p.close()


async def test_pool_new_request_behind_waiters_can_time_out(driver):
    p = pool(driver, size=1, overflow=0, timeout=0.05)
    raw = await p.get()
    first = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    await p.put(raw)
    second = asyncio.create_task(p.get())
    assert await first is raw
    async with asyncio.timeout(2):
        with pytest.raises(exc.TimeoutError):
            await second
    await p.put(raw)
    await p.close()


async def test_pool_timed_out_waiter_frees_its_place(driver):
    p = pool(driver, size=1, overflow=0, timeout=0.01)
    raw = await p.get()
    with pytest.raises(exc.TimeoutError):
        await p.get()
    await p.put(raw)
    assert await p.get() is raw
    await p.put(raw)
    await p.close()


async def test_pool_refuses_requests_beyond_max_waiting(driver):
    p = pool(driver, size=1, overflow=0, timeout=5, max_waiting=1)
    raw = await p.get()
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    with pytest.raises(exc.TooManyWaiting):
        await p.get()
    assert not waiter.done()
    await p.put(raw)
    assert await waiter is raw
    await p.put(raw)
    await p.close()


async def test_pool_max_waiting_zero_never_waits(driver):
    p = pool(driver, size=1, overflow=0, timeout=5, max_waiting=0)
    raw = await p.get()
    with pytest.raises(exc.TooManyWaiting):
        await p.get()
    await p.put(raw)
    assert await p.get() is raw
    await p.put(raw)
    await p.close()


async def test_pool_timed_out_waiter_makes_room_for_the_next(driver):
    p = pool(driver, size=1, overflow=0, timeout=0.01, max_waiting=1)
    raw = await p.get()
    for _ in range(2):
        with pytest.raises(exc.TimeoutError) as info:
            await p.get()
        assert not isinstance(info.value, exc.TooManyWaiting)
    await p.put(raw)
    await p.close()


async def test_pool_cancelled_waiter_makes_room_for_the_next(driver):
    p = pool(driver, size=1, overflow=0, timeout=5, max_waiting=1)
    raw = await p.get()
    cancelled = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    await p.put(raw)
    assert await waiter is raw
    await p.put(raw)
    await p.close()


@pytest.mark.parametrize(
    "options",
    [{"max_waiting": -1}, {"max_waiting": 1, "overflow": -1}],
)
async def test_pool_rejects_pointless_max_waiting(driver, options):
    with pytest.raises(ValueError, match="max_waiting"):
        pool(driver, **options)


async def test_pool_stats_count_checkouts_and_connections(driver):
    p = pool(driver, size=1, overflow=2)
    fresh = p.stats()
    assert (fresh.size, fresh.max_size) == (1, 3)
    assert fresh.checkouts == fresh.opened == fresh.open == 0
    raw = await p.get()
    stats = p.stats()
    assert (stats.open, stats.idle, stats.in_use) == (1, 0, 1)
    assert stats.checkouts == stats.opened == 1
    await p.put(raw)
    assert p.stats().idle == 1
    assert await p.get() is raw
    stats = p.stats()
    assert stats.checkouts == 2
    assert stats.opened == 1
    await p.put(raw)
    await p.close()
    stats = p.stats()
    assert stats.closed_shutdown == stats.opened == stats.closed == 1


async def test_pool_stats_count_waits_timeouts_and_rejections(driver):
    p = pool(driver, size=1, overflow=0, timeout=0.02, max_waiting=1)
    raw = await p.get()
    with pytest.raises(exc.TimeoutError):
        await p.get()
    stats = p.stats()
    assert stats.waits == stats.timeouts == 1
    assert stats.wait_time >= 0.01
    assert stats.waiting == 0
    waiter = asyncio.create_task(p.get())
    await asyncio.sleep(0)
    assert p.stats().waiting == 1
    with pytest.raises(exc.TooManyWaiting):
        await p.get()
    assert p.stats().rejected == 1
    await p.put(raw)
    assert await waiter is raw
    stats = p.stats()
    assert stats.waits == 2
    assert stats.waiting == 0
    assert stats.checkouts == 2
    await p.put(raw)
    await p.close()


async def test_pool_stats_count_failed_connects(driver, monkeypatch):
    p = pool(driver, size=1)

    async def failing(**kwargs):
        raise exc.ConnectionError

    with monkeypatch.context() as patch:
        patch.setattr(p._conn, "create_conn", failing)
        with pytest.raises(exc.ConnectionError):
            await p.get()
    stats = p.stats()
    assert stats.connect_errors == 1
    assert stats.opened == stats.checkouts == 0
    await p.close()


async def test_pool_stats_tell_why_connections_closed(driver, clock):
    p = pool(driver, size=1, max_idle=100)
    first, second = await p.get(), await p.get()
    await p.put(first)
    await p.put(second)
    assert p.stats().closed_surplus == 1
    clock.now += 100
    raw = await p.get()
    assert p.stats().closed_expired == 1
    await driver.close(raw)
    await p.put(raw)
    assert p.stats().closed_broken == 1
    await p.put(await p.get())
    await p.close()
    stats = p.stats()
    assert stats.closed_shutdown == 1
    assert stats.closed == stats.opened == 4
    assert stats.open == 0


async def test_pool_stats_count_connection_lost_at_checkout(driver):
    p = pool(driver, size=1, pessimistic=True)
    raw = await p.get()
    await p.put(raw)
    await driver.close(raw)
    fresh = await p.get()
    assert p.stats().closed_broken == 1
    assert p.stats().opened == 2
    await p.put(fresh)
    await p.close()


async def test_database_pool_stats(driver):
    db = AsyncDatabase(driver.uri.replace("://", "+pool://", 1), size=1)
    async with db.cursor as cur:
        await cur.query("SELECT 1").value()
    stats = db.pool_stats()
    assert stats is not None
    assert stats.checkouts == 1
    await db.close()


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
    assert p.stats().closed_broken == 1
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
    assert p.stats().closed_shutdown == 1


async def test_pool_keeps_autocommit_until_a_checkout_needs_another_mode(
    driver,
):
    p = pool(driver, size=1)
    raw = await p.get(autocommit=True)
    await p.put(raw)
    assert driver.autocommit(raw)
    assert await p.get(autocommit=True) is raw
    assert driver.autocommit(raw)
    await p.put(raw)
    assert await p.get() is raw
    assert not driver.autocommit(raw)
    await p.put(raw)
    assert not driver.autocommit(raw)
    await p.close()


async def test_pool_replaces_connection_past_max_lifetime(driver, clock):
    p = pool(driver, size=1, overflow=0, timeout=1, max_lifetime=100)
    raw = await p.get()
    await p.put(raw)
    clock.now += 94
    assert await p.get() is raw
    await p.put(raw)
    clock.now += 6
    fresh = await p.get()
    assert fresh is not raw
    assert driver.closed(raw)
    assert p.checkedout == 1
    assert p.checkedin == 0
    await p.put(fresh)
    assert p.checkedin == 1
    assert p.checkedout == 0
    await p.close()


async def test_pool_closes_returned_connection_past_max_lifetime(
    driver, clock
):
    p = pool(driver, size=1, overflow=0, timeout=1, max_lifetime=100)
    raw = await p.get()
    clock.now += 100
    assert not driver.closed(raw)
    await p.put(raw)
    assert driver.closed(raw)
    assert p.checkedin == 0
    assert p.checkedout == 0
    await p.close()


@pytest.mark.parametrize("limits", [{}, {"max_lifetime": 100}])
async def test_pool_reuses_in_order_of_return_without_max_idle(driver, limits):
    p = pool(driver, size=2, **limits)
    first, second = await p.get(), await p.get()
    await p.put(first)
    await p.put(second)
    assert await p.get() is first
    await p.put(first)
    await p.close()
    await p.put(await p.get())
    await driver.close(second)


async def test_pool_surplus_connections_reach_max_idle(driver, clock):
    p = pool(driver, size=3, max_idle=100)
    raws = [await p.get() for _ in range(3)]
    for raw in raws:
        await p.put(raw)
    busy = raws[-1]
    for _ in range(3):
        clock.now += 40
        assert await p.get() is busy
        await p.put(busy)
    assert [driver.closed(raw) for raw in raws] == [True, True, False]
    assert p.checkedin == 1
    assert p.checkedout == 0
    assert p.overflow == -2
    await p.close()


async def test_pool_closes_idle_connections_on_return(driver, clock):
    p = pool(driver, size=2, max_idle=100)
    first, second = await p.get(), await p.get()
    await p.put(first)
    clock.now += 100
    await p.put(second)
    assert driver.closed(first)
    assert not driver.closed(second)
    assert p.checkedin == 1
    await p.close()


async def test_pool_cancelled_discard_of_expired_frees_slot(
    driver, clock, monkeypatch
):
    p = pool(driver, size=2, overflow=0, max_idle=100)
    first, second = await p.get(), await p.get()
    await p.put(first)
    await p.put(second)
    clock.now += 100

    async def cancelled(conn):
        raise asyncio.CancelledError

    with monkeypatch.context() as patch:
        patch.setattr(p._conn, "discard", cancelled)
        with pytest.raises(asyncio.CancelledError):
            await p.get()
    assert p.checkedout == 0
    assert p.checkedin == 1
    await driver.close(first)
    async with asyncio.timeout(1):
        fresh = await p.get()
    assert driver.closed(second)
    await p.put(fresh)
    await p.close()


@pytest.mark.parametrize("option", ["max_lifetime", "max_idle"])
async def test_pool_rejects_limits_that_are_not_positive(driver, option):
    with pytest.raises(ValueError, match=option):
        pool(driver, **{option: 0})


async def test_database_replaces_connection(driver, clock):
    uri = driver.uri.replace("://", "+pool://", 1)
    db = AsyncDatabase(uri, max_lifetime=100)
    for opened, seconds in ((1, 0), (1, 0), (2, 100)):
        clock.now += seconds
        async with db.cursor as cur:
            assert await cur.query("SELECT 1").value() == 1
        stats = db.pool_stats()
        assert stats is not None
        assert stats.opened == opened
    await db.close()


def test_pool_refuses_persistent_connections(driver):
    with pytest.raises(ValueError):
        pool(driver, persist=True)
