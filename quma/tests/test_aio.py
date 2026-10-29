import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from .. import (
    AsyncCursor,
    AsyncDatabase,
    Database,
    exc,
)
from ..aio import (
    AsyncPool,
    AsyncQuery,
)
from . import util

pytest.importorskip("psycopg")

pytestmark = [pytest.mark.anyio, pytest.mark.postgres]

URI = util.pg_uri("psycopg")
POOL_URI = util.pg_uri("psycopg+pool")


@dataclass
class User:
    name: str
    email: str
    city: str


def setup_function(function):
    util.setup_pg_db()


@pytest.fixture(params=["plain", "pool"])
async def adb(request, pyformat_sqldirs):
    uri = POOL_URI if request.param == "pool" else URI
    db = AsyncDatabase(uri, pyformat_sqldirs, changeling=True)
    yield db
    await db.close()


@pytest.fixture
async def apooldb(pyformat_sqldirs):
    db = AsyncDatabase(
        POOL_URI, pyformat_sqldirs, changeling=True, size=1, overflow=0
    )
    yield db
    await db.close()


async def test_create_does_no_io(pyformat_sqldirs):
    db = AsyncDatabase(URI + "_wrong", pyformat_sqldirs, persist=True)
    with pytest.raises(exc.ConnectionError):
        await db.open()
    await db.close()


async def test_async_with_opens_and_closes(pyformat_sqldirs):
    async with AsyncDatabase(POOL_URI, pyformat_sqldirs) as db:
        pool = db.conn
        assert isinstance(pool, AsyncPool)
        assert pool.checkedin == 1
    assert db.conn is None
    assert pool.checkedin == 0
    await db.close()


async def test_closed_database(pyformat_sqldirs):
    db = AsyncDatabase(URI, pyformat_sqldirs)
    await db.close()
    with pytest.raises(exc.APIError):
        async with db.cursor:
            pass
    with pytest.raises(exc.APIError):
        await db.open()


async def test_unsupported_driver(pyformat_sqldirs):
    pytest.importorskip("psycopg2")
    with pytest.raises(ValueError, match="no async support"):
        AsyncDatabase(util.pg_uri("psycopg2"), pyformat_sqldirs)


async def test_query_methods(adb):
    async with adb.cursor as cur:
        assert len(await cur.users.all().all()) == 7
        user = await cur.users.by_name(name="User 1").one()
        assert user.email == "user.1@example.com"
        assert user["city"] == "City A"
        assert await cur.users.by_name(name="User 1").value() == (
            "user.1@example.com"
        )
        assert await cur.users.by_name(name="User 1").value("city") == "City A"
        assert (await cur.users.by_city(city="City C").first())[0] == "User 5"
        assert await cur.users.none().first() is None
        assert await cur.users.by_city(city="City B").count() == 2
        assert await cur.users.by_city(city="City B").exists()
        assert not await cur.users.none().exists()
        with pytest.raises(exc.DoesNotExistError):
            await cur.users.none().one()
        with pytest.raises(exc.MultipleRowsError):
            await cur.users.by_city(city="City A").one()
        query = cur.users.by_email("user.3@example.com", 1)
        assert isinstance(query, AsyncQuery)
        assert await query.run() is query
        assert query.rowcount == 1
        assert (await query.one()).name == "User 3"


async def test_iteration(adb):
    async with adb.cursor as cur:
        names = [row.name async for row in cur.users.all()]
        assert names == [f"User {i}" for i in range(1, 8)]
        bunched = [row.name async for row in cur.users.all().unbunch(3)]
        assert bunched == names
        many = cur.users.all().many()
        assert len(await many.get(4)) == 4
        assert len(await many.get(4)) == 3
        assert await many.get(4) == []


async def test_mapping(adb):
    async with adb.cursor as cur:
        user = await cur.users.by_name(name="User 2").one(dict)
        assert user == {
            "email": "user.2@example.com",
            "city": "City A",
            "count": 13,
            "count2": 13,
        }
        users = await cur.query(
            "SELECT name, email, city FROM users ORDER BY id"
        ).all(User)
        assert users[0] == User("User 1", "user.1@example.com", "City A")
        first = await cur.users.by_city(city="City C").first(dict)
        assert first == {"name": "User 5", "email": "user.5@example.com"}
        mapped = [
            u.name
            async for u in cur.query(
                "SELECT name, email, city FROM users ORDER BY id"
            ).unbunch(5, User)
        ]
        assert len(mapped) == 7
        many = cur.query("SELECT name, email, city FROM users").many()
        assert isinstance((await many.get(2, User))[0], User)


async def test_sync_dunders_raise(adb):
    async with adb.cursor as cur:
        query = cur.users.all()
        with pytest.raises(TypeError, match="count"):
            len(query)
        with pytest.raises(TypeError, match="exists"):
            bool(query)
        with pytest.raises(TypeError, match="async for"):
            iter(query)
        with pytest.raises(TypeError, match="first"):
            query[0]


async def test_script_called_with_cursor(adb):
    async with adb.cursor as cur:
        query = adb.users.by_name(cur, name="User 4")
        assert isinstance(query, AsyncQuery)
        assert (await query.one()).city == "City B"
        assert (await adb.user.by_name(cur, name="User 4").one()).city == (
            "City B"
        )


async def test_ad_hoc_queries(adb):
    pytest.importorskip("mako")
    async with adb.cursor as cur:
        row = await cur.query(
            "SELECT name FROM users WHERE city = %(city)s ORDER BY id",
            city="City B",
        ).first()
        assert row.name == "User 3"
        row = await cur.query(
            "SELECT ${column} FROM users WHERE id = %(id)s",
            is_template=True,
            column="email",
            id=2,
        ).one()
        assert row.email == "user.2@example.com"


async def test_cursor_without_block(adb):
    cur = await adb.cursor()
    assert isinstance(cur, AsyncCursor)
    with pytest.raises(exc.APIError, match="already open"):
        await cur
    assert await cur.users.all().count() == 7
    await cur.close()
    async with await adb.cursor() as cur:
        assert await cur.users.all().count() == 7
    assert cur.raw_conn is None


async def test_autocommit(adb, pyformat_sqldirs):
    async with adb.cursor(autocommit=True) as cur:
        assert cur.raw_conn.autocommit
        await cur.users.remove(name="User 1").run()
    async with adb(autocommit=True).cursor as cur:
        assert cur.raw_conn.autocommit
    async with adb.cursor as cur:
        assert not cur.raw_conn.autocommit
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


async def test_contextcommit(pyformat_sqldirs):
    db = AsyncDatabase(POOL_URI, pyformat_sqldirs, contextcommit=True)
    async with db.cursor as cur:
        await cur.users.remove(name="User 1").run()
    with pytest.raises(ValueError):
        async with db.cursor as cur:
            await cur.users.remove(name="User 2").run()
            raise ValueError
    carrier = SimpleNamespace()
    with pytest.raises(ValueError):
        async with db(carrier).cursor as cur:
            await cur.users.remove(name="User 3").run()
            raise ValueError
    # Commits the carried connection's transaction on exit.
    async with db(carrier).cursor:
        pass
    await db.release(carrier)
    async with db.cursor as cur:
        names = [row["name"] async for row in cur.users.all()]
        assert names == [f"User {i}" for i in range(2, 8)]
    await db.close()


async def test_failed_contextcommit_returns_connection(pyformat_sqldirs):
    psycopg = pytest.importorskip("psycopg")
    db = AsyncDatabase(POOL_URI, size=1, contextcommit=True)
    with pytest.raises(psycopg.IntegrityError):
        async with db.cursor as cur:
            await cur.execute(
                "CREATE TEMP TABLE deferred "
                "(id integer UNIQUE DEFERRABLE INITIALLY DEFERRED)"
            )
            await cur.execute("INSERT INTO deferred VALUES (1), (1)")
    assert isinstance(db.conn, AsyncPool)
    assert db.conn.checkedout == 0
    await db.close()


async def test_carrier(adb):
    carrier = SimpleNamespace()
    async with adb(carrier).cursor as cur:
        assert await cur.users.all().count() == 7
        raw_conn = cur.raw_conn
    async with adb(carrier).cursor as cur:
        assert cur.raw_conn is raw_conn
    await cur.close()
    assert not adb.heap.heap
    async with adb(carrier).cursor:
        pass
    assert adb.heap.heap
    await adb.release(carrier)
    await adb.release(carrier)
    assert not adb.heap.heap


async def test_tasks_on_one_carrier_share_its_connection(pyformat_sqldirs):
    db = AsyncDatabase(
        POOL_URI, pyformat_sqldirs, size=2, overflow=0, timeout=1
    )
    carrier = SimpleNamespace()

    async def backend_pid():
        async with db(carrier).cursor as cur:
            return (await cur.query("SELECT pg_backend_pid()").one())[0]

    first, second = await asyncio.gather(backend_pid(), backend_pid())
    assert first == second
    await db.release(carrier)
    assert isinstance(db.conn, AsyncPool)
    assert db.conn.checkedout == 0
    await db.close()


async def test_open_cursor_cannot_be_opened_again(apooldb):
    async with apooldb.cursor as cur:
        with pytest.raises(exc.APIError, match="already open"):
            await cur
        with pytest.raises(exc.APIError, match="already open"):
            async with cur:
                pass
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
    async with cur:
        assert await cur.users.all().count() == 7


async def test_busy_cursor_refuses_commit(apooldb):
    async with apooldb.cursor as cur:
        query = asyncio.create_task(cur.query("SELECT pg_sleep(0.05)").run())
        await asyncio.sleep(0.01)
        with pytest.raises(exc.APIError, match="busy"):
            await cur.commit()
        await query


async def test_one_task_per_cursor(apooldb):
    async with apooldb.cursor as cur:
        with pytest.raises(exc.APIError, match="busy"):
            await asyncio.gather(
                cur.query("SELECT pg_sleep(0.05)").run(),
                cur.users.all().all(),
            )


async def test_one_cursor_per_task(pyformat_sqldirs):
    db = AsyncDatabase(POOL_URI, pyformat_sqldirs, size=2, overflow=1)

    async def count(city):
        async with db.cursor as cur:
            await cur.query("SELECT pg_sleep(0.02)").run()
            return await cur.users.by_city(city=f"City {city}").count()

    counts = await asyncio.gather(*(count(c) for c in "ABCABC"))
    assert counts == [2, 2, 3, 2, 2, 3]
    assert isinstance(db.conn, AsyncPool)
    assert db.conn.checkedout == 0
    await db.close()


async def test_persistent_connection(pyformat_sqldirs):
    db = AsyncDatabase(URI, pyformat_sqldirs, persist=True)
    async with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    async with db.cursor as cur:
        assert cur.raw_conn is raw_conn
    await db.close()
    assert raw_conn.closed


async def test_execute(adb):
    assert await adb.execute("CREATE TABLE test (id integer)") is None
    await adb.execute("INSERT INTO test VALUES (1), (2)")
    rows = await adb.execute("SELECT id FROM test ORDER BY id")
    assert [row[0] for row in rows] == [1, 2]
    psycopg = pytest.importorskip("psycopg")
    with pytest.raises(psycopg.errors.UndefinedTable):
        await adb.execute("SELECT * FROM missing_table")


async def test_echo(pyformat_sqldirs, capsys):
    db = AsyncDatabase(URI, pyformat_sqldirs, echo=True)
    async with db.cursor as cur:
        await cur.users.by_name(name="User 1").one()
    assert "name = 'User 1'" in capsys.readouterr().out
    await db.close()


async def test_prepare_params(pyformat_sqldirs):
    def prepare(carrier, params):
        params["name"] = "User 6"
        return params

    db = AsyncDatabase(URI, pyformat_sqldirs, prepare_params=prepare)
    async with db.cursor as cur:
        assert (await cur.users.by_name().one())[1] == "City C"
    await db.close()


async def test_namespace_classes(tmp_path):
    users = tmp_path / "users"
    users.mkdir()
    (users / "all.sql").write_text("SELECT name FROM users ORDER BY id")
    (users / "__init__.py").write_text(
        "from quma import Namespace\n"
        "\n"
        "class Users(Namespace):\n"
        "    def kind(self, cursor):\n"
        "        return 'sync'\n"
        "\n"
        "class AsyncUsers(Namespace):\n"
        "    async def first_name(self, cursor):\n"
        "        return (await cursor.users.all().first()).name\n"
    )
    db = AsyncDatabase(URI, tmp_path, changeling=True)
    async with db.cursor as cur:
        assert await cur.users.first_name() == "User 1"
    await db.close()
    sync_db = Database(util.pg_uri("psycopg"), tmp_path)
    with sync_db.cursor as cur:
        assert cur.users.kind() == "sync"


async def test_sync_and_async_database_together(pyformat_sqldirs):
    sync_db = Database(util.pg_uri("psycopg+pool"), pyformat_sqldirs)
    async_db = AsyncDatabase(POOL_URI, pyformat_sqldirs)
    with sync_db.cursor as cur:
        cur.users.remove(name="User 7").run()
        cur.commit()
    async with async_db.cursor as cur:
        assert await cur.users.all().count() == 6
    sync_db.close()
    await async_db.close()


@pytest.mark.parametrize("contextcommit", [False, True])
async def test_lost_connection(contextcommit):
    psycopg = pytest.importorskip("psycopg")
    db = AsyncDatabase(
        POOL_URI, size=1, overflow=0, timeout=0.1, contextcommit=contextcommit
    )
    killer = AsyncDatabase(URI)
    with pytest.raises(psycopg.OperationalError):
        async with db.cursor as cur:
            await cur.execute("SELECT pg_backend_pid()")
            pid = (await cur.fetchone())[0]
            await killer.execute(f"SELECT pg_terminate_backend({pid}, 5000)")
            await cur.execute("SELECT 1")
    async with db.cursor as cur:
        await cur.execute("SELECT 1")
        assert (await cur.fetchone())[0] == 1
    await db.close()
    await killer.close()


async def test_failed_cursor_returns_connection(apooldb):
    psycopg = pytest.importorskip("psycopg")
    async with apooldb.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    await raw_conn.close()
    carrier = SimpleNamespace()
    with pytest.raises(psycopg.Error):
        async with apooldb(carrier).cursor:
            pass
    assert apooldb.heap.get(carrier).conn is None
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
    async with asyncio.timeout(1):
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7


async def test_cancelled_query_returns_connection(apooldb):
    with pytest.raises(TimeoutError):
        async with asyncio.timeout(0.1):
            async with apooldb.cursor as cur:
                await cur.query("SELECT pg_sleep(5)").run()
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
    async with asyncio.timeout(1):
        async with apooldb.cursor as cur:
            assert await cur.users.all().count() == 7


async def test_cancelled_waiter_returns_nothing(apooldb):
    async with apooldb.cursor:
        waiter = asyncio.create_task(apooldb.cursor.__aenter__())
        await asyncio.sleep(0.01)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
    assert isinstance(apooldb.conn, AsyncPool)
    assert apooldb.conn.checkedout == 0
