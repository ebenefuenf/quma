"""The async side of test_lifecycle.py."""

import asyncio
from typing import Any

import pytest

from .. import AsyncDatabase, exc
from . import util

pytestmark = pytest.mark.anyio

SQL = "SELECT 1 AS a"
CONNECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "plain": ("", {}),
    "persist": ("", {"persist": True}),
    "pool": ("+pool", {"size": 1, "overflow": 1, "timeout": 0.2}),
}


@pytest.fixture(
    params=[
        "aiosqlite",
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("asyncmy", marks=pytest.mark.mysql),
    ]
)
def driver(request, tmp_path):
    name = request.param
    pytest.importorskip(name)
    if name == "aiosqlite":
        return f"aiosqlite:///{tmp_path / 'lifecycle.sqlite'}"
    if name == "asyncmy":
        return util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
    return util.pg_uri(name)


@pytest.fixture(params=CONNECTIONS)
async def database(request, driver):
    suffix, options = CONNECTIONS[request.param]
    scheme, rest = driver.split("://", 1)
    db = AsyncDatabase(f"{scheme}{suffix}://{rest}", **options)
    yield db
    await db.close()


async def lose(raw):
    if hasattr(raw, "thread_id"):
        uri = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
        kill = f"KILL {raw.thread_id()}"
    elif hasattr(raw, "info"):
        pid = raw.info.backend_pid
        uri = util.pg_uri("psycopg")
        kill = f"SELECT pg_terminate_backend({pid}, 5000)"
    else:
        await raw.close()
        return
    killer = AsyncDatabase(uri)
    async with killer.cursor as cur:
        await cur.execute(kill)
    await killer.close()
    # MySQL's KILL returns before the connection is gone.
    await asyncio.sleep(0.05)


async def assert_no_slot_lost(db):
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    async with db.cursor as cur:
        assert await cur.query(SQL).value() == 1


async def with_and_with(db):
    async with db.cursor as cur:
        async with cur:
            pass


async def called_and_with(db):
    async with await db.cursor() as cur:
        async with cur:
            pass


async def called_twice(db):
    cur = await db.cursor()
    try:
        await cur()
    finally:
        await cur.close()


async def created_twice(db):
    cur = db.cursor
    await cur.create_cursor()
    try:
        await cur.create_cursor()
    finally:
        await cur.close()


async def with_and_created(db):
    async with db.cursor as cur:
        await cur.create_cursor()


async def carried_with_and_with(db):
    carrier = object()
    try:
        async with db(carrier).cursor as cur:
            async with cur:
                pass
    finally:
        await db.release(carrier)


@pytest.mark.parametrize(
    "open_twice",
    [
        with_and_with,
        called_and_with,
        called_twice,
        created_twice,
        with_and_created,
        carried_with_and_with,
    ],
)
async def test_an_open_cursor_refuses_to_open(database, open_twice):
    with pytest.raises(exc.APIError, match="already open"):
        await open_twice(database)
    await assert_no_slot_lost(database)


async def test_a_closed_cursor_opens_again(database):
    cur = database.cursor
    for _ in range(2):
        async with cur:
            assert await cur.query(SQL).value() == 1
    await cur.create_cursor()
    await cur.close()
    async with cur:
        assert await cur.query(SQL).value() == 1
    await assert_no_slot_lost(database)


USES = {
    "query": lambda cur: cur.query(SQL).all(),
    "execute": lambda cur: cur.execute(SQL),
    "fetchall": lambda cur: cur.fetchall(),
    "fetchone": lambda cur: cur.fetchone(),
    "mogrify": lambda cur: _sync(cur.mogrify, SQL, {}),
    "commit": lambda cur: cur.commit(),
    "rollback": lambda cur: cur.rollback(),
    "block": lambda cur: cur.transaction().__aenter__(),
}


async def _sync(call, *args):
    return call(*args)


@pytest.mark.parametrize("use", USES.values(), ids=USES.keys())
async def test_a_cursor_without_a_connection_says_so(database, use):
    cur = database.cursor
    with pytest.raises(exc.APIError, match="no open connection"):
        await use(cur)
    async with cur:
        await cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        await use(cur)
    await assert_no_slot_lost(database)


@pytest.mark.parametrize("use", ["query", "execute", "fetchall", "mogrify"])
async def test_a_closed_carried_cursor_says_so(database, use):
    carrier = object()
    async with database(carrier).cursor as cur:
        await cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        await USES[use](cur)
    await database.release(carrier)
    await assert_no_slot_lost(database)


async def test_a_closed_carried_cursor_can_still_commit(database):
    carrier = object()
    async with database(carrier).cursor as cur:
        await cur.execute(SQL)
    await cur.commit()
    await database.release(carrier)
    await assert_no_slot_lost(database)


def query(cur):
    return cur.query(SQL).all()


def execute(cur):
    return cur.execute(SQL)


async def stream(cur):
    async for row in cur.query(SQL).stream():
        return row


async def block(cur):
    async with cur.transaction():
        await cur.query(SQL).all()


@pytest.mark.parametrize("use", [query, execute, stream, block])
async def test_a_lost_connection_raises_connection_lost(database, use):
    async with database.cursor as cur:
        await lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            await use(cur)
        with pytest.raises(exc.ConnectionLost):
            await use(cur)
    await assert_recovers(database)


async def assert_recovers(db):
    """A connection found broken only on its next use costs one statement."""
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    try:
        async with db.cursor as cur:
            await cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    async with db.cursor as cur:
        assert await cur.query(SQL).value() == 1


@pytest.mark.parametrize(
    "use", [lambda cur: cur.commit(), lambda cur: cur.rollback()]
)
async def test_ending_a_transaction_on_a_lost_connection(database, use):
    async with database.cursor as cur:
        await cur.execute(SQL)
        await lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            await use(cur)
    await assert_recovers(database)


async def test_a_block_after_a_failed_statement_on_a_lost_connection(database):
    async with database.cursor as cur:
        await lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            await cur.query(SQL).all()
        with pytest.raises(exc.ConnectionLost):
            async with cur.transaction():
                await cur.query(SQL).all()
    await assert_recovers(database)


async def test_a_lost_connection_keeps_the_exception_of_the_block(database):
    with pytest.raises(ZeroDivisionError):
        async with database.cursor as cur:
            await lose(cur.raw_conn)
            raise ZeroDivisionError
    await assert_recovers(database)


async def test_an_autocommit_cursor_after_a_lost_connection(driver):
    db = AsyncDatabase(driver, persist=True)
    async with db.cursor as cur:
        await cur.execute(SQL)
        raw = cur.raw_conn
    await lose(raw)
    try:
        async with await db.cursor(autocommit=True) as cur:
            await cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    await assert_recovers(db)
    await db.close()


async def test_closing_a_database_with_a_lost_connection(database):
    async with database.cursor as cur:
        await lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            await cur.query(SQL).all()
    await database.close()


async def test_a_closed_persistent_connection_stays_closed(driver):
    db = AsyncDatabase(driver, persist=True)
    cur = db.cursor
    await db.close()
    with pytest.raises(exc.APIError, match="closed"):
        await cur.create_cursor()
