"""The async side of test_lifecycle.py."""

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
