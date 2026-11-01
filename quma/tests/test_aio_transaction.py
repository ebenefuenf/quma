import asyncio

import pytest

from .. import (
    APIError,
    AsyncDatabase,
)
from ..aio import AsyncPool
from . import util

pytest.importorskip("psycopg")
pytest.importorskip("asyncmy")

pytestmark = pytest.mark.anyio

ALREADY_OPEN = "already open"
NO_COMMIT = "can't run in a transaction block"
RETURNED = "before the end of its block"
ABORTED = "aborted the transaction"
MYSQL_STREAM = "MySQL can't run"

PG_URI = util.pg_uri("psycopg")
PG_POOL_URI = util.pg_uri("psycopg+pool")
MY_URI = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
MY_POOL_URI = util.MYSQL_POOL_URI.replace(
    "mysqlclient+pool://", "asyncmy+pool://"
)

DRIVERS = [
    pytest.param(PG_URI, id="psycopg", marks=pytest.mark.postgres),
    pytest.param(PG_POOL_URI, id="psycopg+pool", marks=pytest.mark.postgres),
    pytest.param(MY_URI, id="asyncmy", marks=pytest.mark.mysql),
    pytest.param(MY_POOL_URI, id="asyncmy+pool", marks=pytest.mark.mysql),
]


def prepare(uri):
    if uri.startswith("psycopg"):
        util.setup_pg_db()
    else:
        util.setup_mysql_db()
    return uri


@pytest.fixture(params=DRIVERS)
async def open_db(request, named_sqldirs):
    uri = prepare(request.param)
    dbs = []

    def create(**kwargs):
        dbs.append(AsyncDatabase(uri, named_sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        await db.close()


@pytest.fixture
def db(open_db):
    return open_db()


@pytest.fixture
async def pg(named_sqldirs):
    util.setup_pg_db()
    db = AsyncDatabase(PG_URI, named_sqldirs)
    yield db
    await db.close()


@pytest.fixture
async def my(named_sqldirs):
    util.setup_mysql_db()
    db = AsyncDatabase(MY_URI, named_sqldirs)
    yield db
    await db.close()


async def move(cur, *ids):
    for id_ in ids:
        await cur.query(
            "UPDATE users SET city = 'Moved' WHERE id = :id", id=id_
        ).run()


async def moved_on(cur):
    sql = "SELECT id FROM users WHERE city = 'Moved' ORDER BY id"
    return [row[0] for row in await cur.query(sql).all()]


async def moved(db):
    async with db.cursor as cur:
        return await moved_on(cur)


async def test_commits_at_its_end(db):
    async with db.cursor as cur, cur.transaction():
        await move(cur, 1)
    assert await moved(db) == [1]


async def test_rolls_back_on_exception(db):
    with pytest.raises(ValueError, match="in the block"):
        async with db.cursor as cur, cur.transaction():
            await move(cur, 1)
            raise ValueError("in the block")
    assert await moved(db) == []


async def test_nested_rolls_back_only_its_own_work(db):
    async with db.cursor as cur, cur.transaction():
        await move(cur, 1)
        with pytest.raises(ValueError):
            async with cur.transaction():
                await move(cur, 2)
                raise ValueError
        async with cur.transaction():
            await move(cur, 3)
            async with cur.transaction():
                await move(cur, 4)
    assert await moved(db) == [1, 3, 4]


async def test_outer_rolls_back_nested(db):
    with pytest.raises(ValueError):
        async with db.cursor as cur, cur.transaction():
            async with cur.transaction():
                await move(cur, 1)
            raise ValueError
    assert await moved(db) == []


async def test_refuses_open_transaction(db):
    async with db.cursor as cur:
        await move(cur, 1)
        with pytest.raises(APIError, match=ALREADY_OPEN):
            async with cur.transaction():
                pytest.fail("The block must not run")
        await cur.rollback()
        async with cur.transaction():
            await move(cur, 2)
    assert await moved(db) == [2]


async def test_commit_and_rollback_refused_inside(db):
    async with db.cursor as cur, cur.transaction():
        await move(cur, 1)
        with pytest.raises(APIError, match=NO_COMMIT):
            await cur.commit()
        with pytest.raises(APIError, match=NO_COMMIT):
            await cur.rollback()
    assert await moved(db) == [1]


async def test_keeps_unread_result(db):
    async with db.cursor as cur, cur.transaction():
        query = await cur.users.all().run()
        async with cur.transaction():
            pass
        assert len(await query.all()) == 7


async def check_autocommit(db, cursor):
    async with cursor() as cur:
        assert await cur.users.all().all()
        await move(cur, 1)
        with pytest.raises(ValueError):
            async with cur.transaction():
                await move(cur, 2)
                raise ValueError
        async with cur.transaction():
            await move(cur, 3)
            with pytest.raises(ValueError):
                async with cur.transaction():
                    await move(cur, 4)
                    raise ValueError
        await move(cur, 5)
    assert await moved(db) == [1, 3, 5]


async def test_autocommit_cursor(db):
    await check_autocommit(db, lambda: db.cursor(autocommit=True))


async def test_autocommit_database(open_db):
    db = open_db(autocommit=True)
    await check_autocommit(db, lambda: db.cursor)


async def test_default_database_keeps_rolling_back(db):
    async with db.cursor as cur:
        await move(cur, 1)
    assert await moved(db) == []


async def test_carried_cursors_share_a_block(db):
    carrier = object()
    try:
        async with db(carrier).cursor as cur, cur.transaction():
            await move(cur, 1)
            async with db(carrier).cursor as other:
                with pytest.raises(ValueError):
                    async with other.transaction():
                        await move(other, 2)
                        raise ValueError
                await move(other, 3)
    finally:
        await db.release(carrier)
    assert await moved(db) == [1, 3]


async def test_carried_contextcommit_leaves_it_to_the_block(open_db):
    db = open_db(contextcommit=True)
    carrier = object()
    try:
        with pytest.raises(ValueError):
            async with db(carrier).cursor as cur, cur.transaction():
                async with db(carrier).cursor as other:
                    await move(other, 1)
                raise ValueError
    finally:
        await db.release(carrier)
    assert await moved(db) == []


async def test_connection_returned_in_block(db):
    with pytest.raises(APIError, match=RETURNED):
        async with db.cursor as cur, cur.transaction():
            await move(cur, 1)
            await cur.close()
    assert await moved(db) == []


@pytest.mark.parametrize(
    "uri",
    [
        pytest.param(PG_POOL_URI, id="psycopg", marks=pytest.mark.postgres),
        pytest.param(MY_POOL_URI, id="asyncmy", marks=pytest.mark.mysql),
    ],
)
async def test_cancelled_block_rolls_back(uri, named_sqldirs):
    db = AsyncDatabase(prepare(uri), named_sqldirs, size=1, overflow=0)
    started = asyncio.Event()

    async def work():
        async with db.cursor as cur, cur.transaction():
            await move(cur, 1)
            started.set()
            await asyncio.sleep(10)

    task = asyncio.create_task(work())
    await started.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert isinstance(db.conn, AsyncPool)
    assert db.conn.checkedout == 0
    async with asyncio.timeout(1):
        assert await moved(db) == []
    await db.close()


@pytest.mark.postgres
async def test_postgres_read_opens_transaction(pg):
    async with pg.cursor as cur:
        assert await cur.query("SELECT 1 AS one").value() == 1
        with pytest.raises(APIError, match=ALREADY_OPEN):
            async with cur.transaction():
                pytest.fail("The block must not run")


@pytest.mark.postgres
async def test_postgres_failed_statement_prevents_commit(pg):
    import psycopg

    with pytest.raises(APIError, match=ABORTED):
        async with pg.cursor as cur, cur.transaction():
            await move(cur, 1)
            with pytest.raises(psycopg.Error):
                await cur.query("SELECT 1 / 0").run()
    assert await moved(pg) == []


@pytest.mark.postgres
async def test_postgres_stream_in_block_on_autocommit_cursor(pg):
    async with pg.cursor(autocommit=True) as cur:
        with pytest.raises(APIError, match="in transactions only"):
            await anext(cur.users.all().stream())
        async with cur.transaction():
            rows = [row async for row in cur.users.all().stream(3)]
            assert len(rows) == 7


@pytest.mark.mysql
async def test_mysql_detects_open_transaction(my):
    async with my.cursor as cur:
        assert await cur.query("SELECT 1 AS one").value() == 1
        async with cur.transaction():
            pass
        assert await cur.query("SELECT * FROM users").all()
        with pytest.raises(APIError, match=ALREADY_OPEN):
            async with cur.transaction():
                pytest.fail("The block must not run")


@pytest.mark.mysql
async def test_mysql_stream_prevents_commit_and_block_rolls_back(my):
    with pytest.raises(APIError, match=MYSQL_STREAM):
        async with my.cursor as cur, cur.transaction():
            await move(cur, 1)
            rows = cur.users.all().stream(1)
            await anext(rows)
    assert await moved(my) == []
    await rows.aclose()


# asyncmy would warn about dropping the rest of an open stream.
@pytest.mark.filterwarnings("error")
@pytest.mark.mysql
async def test_mysql_exception_with_open_stream_rolls_back(my):
    carrier = object()
    try:
        with pytest.raises(ValueError):
            async with my(carrier).cursor as cur, cur.transaction():
                await move(cur, 1)
                rows = cur.users.all().stream(1)
                await anext(rows)
                raise ValueError
        async with my(carrier).cursor as cur:
            assert await moved_on(cur) == []
    finally:
        await my.release(carrier)
    await rows.aclose()
