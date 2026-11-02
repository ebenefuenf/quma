import asyncio
import inspect
from types import SimpleNamespace

import pytest

from .. import (
    AsyncDatabase,
    ProgrammingError,
)
from ..aio.database import connect_async
from ..aio.pool import AsyncPool
from . import util

pytestmark = pytest.mark.anyio


def connect_pool(uri, **kwargs):
    pool = connect_async(uri, **kwargs)
    assert isinstance(pool, AsyncPool)
    return pool


async def execute(conn, sql):
    # aiosqlite's cursor() has to be awaited.
    cur = conn.cursor()
    if inspect.isawaitable(cur) and not hasattr(cur, "execute"):
        cur = await cur
    await cur.execute(sql)
    await cur.close()


@pytest.fixture(
    params=[
        "aiosqlite",
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("asyncmy", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    pytest.importorskip(request.param)
    calls = []
    if request.param == "aiosqlite":
        uri = f"aiosqlite:///{util.SQLITE_FILE}"
        spec = dict(
            uri=uri,
            pool_uri=uri.replace("aiosqlite://", "aiosqlite+pool://"),
            setup="PRAGMA foreign_keys = ON",
            check="PRAGMA foreign_keys",
            value=1,
            closed=lambda raw: raw._connection is None,
            close=lambda raw: raw.close(),
        )
    elif request.param == "psycopg":
        spec = dict(
            uri=util.pg_uri("psycopg"),
            pool_uri=util.pg_uri("psycopg+pool"),
            setup="SET application_name = 'quma_on_connect'",
            check="SHOW application_name",
            value="quma_on_connect",
            closed=lambda raw: raw.closed,
            close=lambda raw: raw.close(),
        )
    else:
        uri = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
        spec = dict(
            uri=uri,
            pool_uri=uri.replace("asyncmy://", "asyncmy+pool://"),
            setup="SET @quma_on_connect = 7",
            check="SELECT @quma_on_connect",
            value=7,
            closed=lambda raw: not raw.connected,
            close=lambda raw: raw.ensure_closed(),
        )

    async def hook(conn):
        calls.append(conn)
        await execute(conn, spec["setup"])

    return SimpleNamespace(calls=calls, hook=hook, **spec)


async def test_pool_runs_it_once_per_connection(driver):
    pool = connect_pool(driver.pool_uri, size=2, on_connect=driver.hook)
    first = await pool.get()
    assert driver.calls == [first]
    await pool.put(first)
    assert await pool.get() is first
    assert driver.calls == [first]
    second = await pool.get()
    assert driver.calls == [first, second]
    await pool.put(first)
    await pool.put(second)
    await pool.close()


async def test_plain_function_runs_too(driver):
    calls = []
    db = AsyncDatabase(driver.pool_uri, on_connect=calls.append)
    async with db.cursor as cur:
        assert await cur.query("SELECT 1").value() == 1
    assert len(calls) == 1
    await db.close()


async def test_every_cursor_runs_it_without_a_pool(driver):
    db = AsyncDatabase(driver.uri, on_connect=driver.hook)
    for count in (1, 2):
        async with db.cursor as cur:
            assert await cur.query(driver.check).value() == driver.value
        assert len(driver.calls) == count
    await db.close()


async def test_persistent_connection_runs_it_once_on_first_use(driver):
    db = AsyncDatabase(driver.uri, persist=True, on_connect=driver.hook)
    assert driver.calls == []
    for _ in range(2):
        async with db.cursor as cur:
            assert await cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 1
    await db.close()


async def test_persistent_reconnect_runs_it_again(driver):
    db = AsyncDatabase(
        driver.uri, persist=True, pessimistic=True, on_connect=driver.hook
    )
    async with db.cursor as cur:
        await cur.query(driver.check).value()
    await driver.close(driver.calls[0])
    async with db.cursor as cur:
        assert await cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 2
    await db.close()


async def test_its_settings_survive_returning_the_connection(driver):
    db = AsyncDatabase(driver.pool_uri, size=1, on_connect=driver.hook)
    for _ in range(2):
        async with db.cursor as cur:
            assert await cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 1
    await db.close()


async def test_transaction_block_can_start_right_after_it(driver):
    db = AsyncDatabase(driver.pool_uri, size=1, on_connect=driver.hook)
    async with db.cursor as cur, cur.transaction():
        assert await cur.query(driver.check).value() == driver.value
    await db.close()


async def test_it_runs_before_autocommit_applies(driver):
    modes = []

    async def hook(conn):
        modes.append(pool.in_autocommit(conn))
        await driver.hook(conn)

    pool = connect_pool(driver.pool_uri, size=1, on_connect=hook)
    raw = await pool.get(autocommit=True)
    assert modes == [False]
    assert pool.in_autocommit(raw)
    await pool.put(raw)
    await pool.close()


async def test_autocommit_left_on_doesnt_reach_the_cursor(driver):
    async def hook(conn):
        await pool._conn.enable_autocommit_if(True, conn)

    pool = connect_pool(driver.pool_uri, size=1, on_connect=hook)
    raw = await pool.get()
    assert not pool.in_autocommit(raw)
    await pool.put(raw)
    await pool.close()


@pytest.mark.parametrize("error", [ZeroDivisionError, asyncio.CancelledError])
async def test_exception_closes_the_connection_and_frees_the_slot(
    driver, error
):
    async def hook(conn):
        driver.calls.append(conn)
        if len(driver.calls) == 1:
            raise error

    pool = connect_pool(
        driver.pool_uri, size=1, overflow=0, timeout=1, on_connect=hook
    )
    with pytest.raises(error):
        await pool.get()
    assert driver.closed(driver.calls[0])
    assert pool.checkedout == 0
    raw = await pool.get()
    assert raw is driver.calls[1]
    await pool.put(raw)
    await pool.close()


async def test_driver_error_becomes_quma_exception(driver):
    async def hook(conn):
        driver.calls.append(conn)
        await execute(conn, "SELECT * FROM quma_table_that_does_not_exist")

    pool = connect_pool(driver.pool_uri, size=1, overflow=0, on_connect=hook)
    with pytest.raises(ProgrammingError) as info:
        await pool.get()
    assert isinstance(info.value.__cause__, pool.driver_error)
    assert driver.closed(driver.calls[0])
    assert pool.checkedout == 0
    await pool.close()
