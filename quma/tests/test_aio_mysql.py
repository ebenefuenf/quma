import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from .. import (
    AsyncDatabase,
    Database,
    exc,
)
from ..aio import AsyncPool
from . import util

asyncmy = pytest.importorskip("asyncmy")

pytestmark = [pytest.mark.anyio, pytest.mark.mysql]

URI = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
POOL_URI = util.MYSQL_POOL_URI.replace(
    "mysqlclient+pool://", "asyncmy+pool://"
)


@dataclass
class User:
    name: str
    email: str
    city: str


def setup_function(function):
    util.setup_mysql_db()


@pytest.fixture(params=["plain", "pool"])
async def adb(request, named_sqldirs):
    uri = POOL_URI if request.param == "pool" else URI
    db = AsyncDatabase(uri, named_sqldirs)
    yield db
    await db.close()


@pytest.fixture(params=["plain", "pool"])
async def adb_dict(request, named_sqldirs):
    uri = POOL_URI if request.param == "pool" else URI
    db = AsyncDatabase(uri, named_sqldirs, dict_cursor=True)
    yield db
    await db.close()


@pytest.fixture
async def apooldb(named_sqldirs):
    db = AsyncDatabase(POOL_URI, named_sqldirs, size=1, overflow=0)
    yield db
    await db.close()


def test_sync_database_refuses_driver(named_sqldirs):
    with pytest.raises(ValueError, match="async only"):
        Database(URI, named_sqldirs)


async def test_query_methods(adb):
    async with adb.cursor as cur:
        assert len(await cur.users.all().all()) == 7
        user = await cur.users.by_name(name="User 1").one()
        assert user[0] == "user.1@example.com"
        assert await cur.users.by_name(name="User 1").value() == (
            "user.1@example.com"
        )
        assert (await cur.users.by_city(city="City C").first())[0] == "User 5"
        assert await cur.users.none().first() is None
        assert await cur.users.by_city(city="City B").count() == 2
        assert await cur.users.by_city(city="City B").exists()
        assert not await cur.users.none().exists()
        with pytest.raises(exc.DoesNotExistError):
            await cur.users.none().one()
        with pytest.raises(exc.MultipleRowsError):
            await cur.users.by_city(city="City A").one()
        query = cur.users.by_name(name="User 3")
        assert (await query.run()).rowcount == 1
        assert (await query.one())[0] == "user.3@example.com"


async def test_dict_rows(adb_dict):
    async with adb_dict.cursor as cur:
        user = await cur.users.by_name(name="User 3").one()
        assert user["email"] == "user.3@example.com"
        with pytest.raises(KeyError):
            user[0]
        assert await cur.users.by_name(name="User 3").value("city") == (
            "City B"
        )


async def test_iteration(adb):
    async with adb.cursor as cur:
        names = [row[1] async for row in cur.users.all()]
        assert names == [f"User {i}" for i in range(1, 8)]
        bunched = [row[1] async for row in cur.users.all().unbunch(3)]
        assert bunched == names
        many = cur.users.all().many()
        assert len(await many.get(4)) == 4
        assert len(await many.get(4)) == 3
        assert not await many.get(4)


async def test_mapping(adb, adb_dict):
    for db in (adb, adb_dict):
        async with db.cursor as cur:
            users = await cur.query(
                "SELECT name, email, city FROM users ORDER BY id"
            ).all(User)
            assert users[0] == User("User 1", "user.1@example.com", "City A")
            first = await cur.users.by_city(city="City C").first(dict)
            assert first == {"name": "User 5", "email": "user.5@example.com"}


async def test_native_placeholders(pyformat_sqldirs):
    db = AsyncDatabase(URI, pyformat_sqldirs, placeholders="native")
    sql = "SELECT name, city FROM users WHERE email = %s AND 1 = %s"
    async with db.cursor as cur:
        assert await cur.query(sql, "user.1@example.com", 1).value() == (
            "User 1"
        )
        user = await cur.user.by_email("user.1@example.com", 1).one()
        assert user[0] == "User 1"
        q = cur.query("SELECT CONCAT('User%%', %(n)s)", n=1)
        assert await q.value() == "User%1"
    await db.close()


async def test_literal_percent(adb):
    sql = "SELECT name FROM users WHERE name LIKE 'User%' AND city = :city"
    async with adb.cursor as cur:
        q = cur.query("SELECT count(*) FROM users WHERE name LIKE 'U%'")
        assert await q.value() == 7
        assert await cur.query(sql, city="City B").count() == 2


async def test_positional_params_need_native(adb):
    async with adb.cursor as cur:
        with pytest.raises(TypeError, match='placeholders="native"'):
            await cur.query("SELECT %s", 1).run()


async def test_autocommit(adb):
    async with adb.cursor(autocommit=True) as cur:
        assert cur.raw_conn.get_autocommit()
        await cur.users.remove(name="User 1").run()
    async with adb.cursor as cur:
        assert not cur.raw_conn.get_autocommit()
        assert await cur.users.all().count() == 6


async def test_commit_and_rollback(adb):
    async with adb.cursor as cur:
        await cur.users.remove(name="User 1").run()
        await cur.rollback()
        assert await cur.users.all().count() == 7
        await cur.users.remove(name="User 1").run()
        await cur.commit()
    async with adb.cursor as cur:
        assert await cur.users.all().count() == 6
        await cur.users.remove(name="User 2").run()
    async with adb.cursor as cur:
        assert await cur.users.all().count() == 6


async def test_contextcommit(named_sqldirs):
    db = AsyncDatabase(POOL_URI, named_sqldirs, contextcommit=True)
    async with db.cursor as cur:
        await cur.users.remove(name="User 1").run()
    with pytest.raises(ValueError):
        async with db.cursor as cur:
            await cur.users.remove(name="User 2").run()
            raise ValueError
    async with db.cursor as cur:
        names = [row[1] async for row in cur.users.all()]
        assert names == [f"User {i}" for i in range(2, 8)]
    await db.close()


async def test_carrier(apooldb):
    carrier = SimpleNamespace()
    async with apooldb(carrier).cursor as cur:
        raw_conn = cur.raw_conn
    async with apooldb(carrier).cursor as cur:
        assert cur.raw_conn is raw_conn
    await apooldb.release(carrier)
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0


async def test_tasks_on_one_carrier_take_turns(apooldb):
    carrier = SimpleNamespace()

    async def select(i):
        async with apooldb(carrier).cursor as cur:
            await cur.execute(f"SELECT {i}, SLEEP(0.02)")
            return (await cur.fetchone())[0]

    async with asyncio.timeout(5):
        assert await asyncio.gather(*(select(i) for i in range(4))) == [
            0,
            1,
            2,
            3,
        ]
    await apooldb.release(carrier)
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0


async def test_close_waits_for_running_query(apooldb):
    async with asyncio.timeout(5):
        cur = await apooldb.cursor()
        running = asyncio.create_task(cur.query("SELECT SLEEP(0.1)").run())
        await asyncio.sleep(0.02)
        await cur.close()
        await running
        assert isinstance(apooldb.conn, AsyncPool)
        assert apooldb.conn.checkedout == 0
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7


async def test_release_waits_for_running_query(apooldb):
    request = SimpleNamespace()
    async with asyncio.timeout(5):
        cur = await apooldb(request).cursor()
        running = asyncio.create_task(cur.query("SELECT SLEEP(0.1)").run())
        await asyncio.sleep(0.02)
        await apooldb.release(request)
        await running
        assert isinstance(apooldb.conn, AsyncPool)
        assert apooldb.conn.checkedout == 0
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7


async def test_persistent_connection(named_sqldirs):
    db = AsyncDatabase(URI, named_sqldirs, persist=True)
    async with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    async with db.cursor as cur:
        assert cur.raw_conn is raw_conn
    await db.close()
    assert not raw_conn.connected


async def test_execute(adb):
    assert await adb.execute("CREATE TABLE test (id integer)") is None
    await adb.execute("INSERT INTO test VALUES (1), (2)")
    rows = await adb.execute("SELECT id FROM test ORDER BY id")
    assert [row[0] for row in rows] == [1, 2]
    await adb.execute("DROP TABLE test")
    with pytest.raises(asyncmy.errors.ProgrammingError):
        await adb.execute("SELECT * FROM missing_table")


async def test_failing_later_statement_returns_connection(apooldb):
    with pytest.raises(asyncmy.errors.ProgrammingError):
        async with apooldb.cursor as cur:
            await cur.execute("SELECT 1; SELECT * FROM missing_table")
            assert (await cur.fetchone())[0] == 1
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
    async with asyncio.timeout(1):
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7


async def test_echo(named_sqldirs, capsys):
    db = AsyncDatabase(URI, named_sqldirs, echo=True)
    async with db.cursor as cur:
        await cur.users.by_name(name="User 1").one()
    assert "name = 'User 1'" in capsys.readouterr().out
    await db.close()


@pytest.mark.parametrize("contextcommit", [False, True])
@pytest.mark.parametrize("pooled", [True, False])
async def test_lost_connection(pooled, contextcommit):
    if pooled:
        db = AsyncDatabase(
            POOL_URI,
            size=1,
            overflow=0,
            timeout=0.1,
            contextcommit=contextcommit,
        )
    else:
        db = AsyncDatabase(
            URI, persist=True, pessimistic=True, contextcommit=contextcommit
        )
    killer = AsyncDatabase(URI)
    with pytest.raises(asyncmy.errors.OperationalError):
        async with db.cursor as cur:
            await cur.execute("SELECT CONNECTION_ID()")
            pid = (await cur.fetchone())[0]
            await killer.execute(f"KILL {pid}")
            await cur.execute("SELECT 1")
    async with db.cursor as cur:
        await cur.execute("SELECT 1")
        assert (await cur.fetchone())[0] == 1
    await db.close()
    await killer.close()


async def test_cancelled_query_returns_connection(apooldb):
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            async with apooldb.cursor as cur:
                await cur.query("SELECT SLEEP(5)").run()
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
    async with asyncio.timeout(1):
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7
