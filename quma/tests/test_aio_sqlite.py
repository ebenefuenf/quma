import asyncio
import subprocess
import sys
from dataclasses import dataclass

import pytest

from .. import (
    AsyncDatabase,
    Database,
    exc,
)
from . import util

pytest.importorskip("aiosqlite")

pytestmark = pytest.mark.anyio

URI = f"aiosqlite:///{util.SQLITE_FILE}"
POOL_URI = f"aiosqlite+pool:///{util.SQLITE_FILE}"
FOREVER = (
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
    "SELECT count(*) FROM c"
)
ROWS_FOREVER = (
    "WITH RECURSIVE c(x) AS (SELECT 1 UNION ALL SELECT x + 1 FROM c) "
    "SELECT x FROM c"
)


@dataclass
class User:
    name: str
    email: str
    city: str


def setup_function(function):
    util.setup_sqlite_db()


@pytest.fixture(params=[URI, POOL_URI], ids=["plain", "pool"])
async def adb(request, named_sqldirs):
    db = AsyncDatabase(request.param, named_sqldirs)
    yield db
    await db.close()


@pytest.fixture(
    params=[
        pytest.param({"persist": True}, id="persistent"),
        pytest.param({}, id="plain"),
    ]
)
async def persistent(request, tmp_path, named_sqldirs):
    db = AsyncDatabase(
        f"aiosqlite:///{tmp_path / 'test.db'}",
        named_sqldirs,
        **request.param,
    )
    yield db
    await db.close()


def test_sync_database_refuses_driver():
    with pytest.raises(ValueError, match="async only"):
        Database(URI)


def test_async_database_points_to_the_driver():
    with pytest.raises(ValueError, match="aiosqlite://"):
        AsyncDatabase(util.SQLITE_URI)


def test_database_path_is_required():
    with pytest.raises(ValueError, match="path"):
        AsyncDatabase("aiosqlite://")


async def test_query_methods(adb):
    async with adb.cursor as cur:
        assert len(await cur.users.all().all()) == 7
        assert await cur.users.all().count() == 7
        assert await cur.users.all().exists()
        assert await cur.users.by_name(name="User 3").value("city") == "City B"
        first = await cur.users.all().first()
        assert first["name"] == "User 1"
        with pytest.raises(exc.MultipleRowsError):
            await cur.users.all().one()
        with pytest.raises(exc.DoesNotExistError):
            await cur.users.by_name(name="nobody").one()


async def test_writes_need_a_commit(adb):
    update = "UPDATE users SET city = :city WHERE id = 1"
    select = "SELECT city FROM users WHERE id = 1"
    async with adb.cursor as cur:
        await cur.query(update, city="Rolled back").run()
        await cur.rollback()
        assert await cur.query(select).value() == "City A"
        await cur.query(update, city="Dropped").run()
    async with adb.cursor as cur:
        assert await cur.query(select).value() == "City A"
        await cur.query(update, city="Kept").run()
        await cur.commit()
    async with adb.cursor as cur:
        assert await cur.query(select).value() == "Kept"


async def test_autocommit(adb):
    update = "UPDATE users SET city = 'Kept' WHERE id = 1"
    async with adb.cursor(autocommit=True) as cur:
        await cur.query(update).run()
    async with adb.cursor as cur:
        select = "SELECT city FROM users WHERE id = 1"
        assert await cur.query(select).value() == "Kept"


async def test_read_opens_no_transaction(adb):
    async with adb.cursor as cur, cur.transaction():
        pass
    async with adb.cursor as cur:
        await cur.users.all().all()
        async with cur.transaction():
            await cur.query("UPDATE users SET city = 'X' WHERE id = 1").run()


async def test_stream(adb):
    async with adb.cursor as cur:
        users = cur.users.all()
        rows = await users.all()
        assert [row async for row in users.stream(3)] == list(rows)
        mapped = [
            user
            async for user in cur.query(
                "SELECT name, email, city FROM users ORDER BY id"
            ).stream(2, User)
        ]
        assert mapped[0] == User("User 1", "user.1@example.com", "City A")


async def test_tasks_on_a_pool_run_in_parallel(named_sqldirs):
    db = AsyncDatabase(POOL_URI, named_sqldirs, size=3)

    async def count():
        async with db.cursor as cur:
            return await cur.users.all().count()

    assert await asyncio.gather(*(count() for _ in range(6))) == [7] * 6
    await db.close()


async def test_memory_database_lives_with_its_connection():
    db = AsyncDatabase("aiosqlite:///:memory:", persist=True)
    async with db.cursor as cur:
        await cur.execute("CREATE TABLE t (id INT)")
        await cur.query("INSERT INTO t VALUES (1)").run()
        await cur.commit()
    async with db.cursor as cur:
        assert await cur.query("SELECT id FROM t").value() == 1
    await db.close()


@pytest.mark.parametrize("sql", [FOREVER, ROWS_FOREVER])
async def test_cancelling_a_query_interrupts_it(persistent, sql):
    async def query():
        async with persistent.cursor as cur:
            await cur.query(sql).all()

    task = asyncio.create_task(query())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(5):
        async with persistent.cursor as cur:
            assert await cur.query("SELECT 1").value() == 1


async def test_cancelled_query_rolls_its_transaction_back(tmp_path):
    db = AsyncDatabase(f"aiosqlite+pool:///{tmp_path / 'test.db'}", size=1)
    async with db.cursor as cur:
        await cur.execute("CREATE TABLE t (id INT)")
        await cur.commit()

    async def query():
        async with db.cursor as cur:
            await cur.query("INSERT INTO t VALUES (1)").run()
            await cur.query(FOREVER).value()

    task = asyncio.create_task(query())
    await asyncio.sleep(0.05)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with asyncio.timeout(5):
        async with db.cursor as cur:
            assert await cur.query("SELECT count(*) FROM t").value() == 0
    stats = db.pool_stats()
    assert stats is not None
    assert stats.in_use == 0
    await db.close()


def test_connection_that_wasnt_closed_lets_the_process_end():
    script = """
import asyncio
from quma import AsyncDatabase

db = AsyncDatabase("aiosqlite:///:memory:", persist=True)

async def main():
    async with db.cursor as cur:
        print(await cur.query("SELECT 1").value())

asyncio.run(main())
"""
    result = subprocess.run(
        [sys.executable, "-W", "ignore", "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.stdout.strip() == "1"
    assert result.returncode == 0


async def test_cursor_before_its_first_statement(adb):
    async with adb.cursor as cur:
        assert cur.description is None
        assert cur.rowcount == -1
        assert cur.lastrowid is None
        await cur.execute("SELECT 1 AS one")
        assert cur.description[0][0] == "one"
        assert cur.arraysize == 1


async def test_errors_are_quma_exceptions(tmp_path):
    db = AsyncDatabase(f"aiosqlite:///{tmp_path / 'e.db'}", persist=True)
    async with db.cursor as cur:
        await cur.execute("PRAGMA foreign_keys = ON")
        await cur.execute(
            "CREATE TABLE parent (id INT PRIMARY KEY, name TEXT UNIQUE NOT NULL)"
        )
        await cur.execute(
            "CREATE TABLE child (parent INT REFERENCES parent (id))"
        )
        await cur.execute("INSERT INTO parent VALUES (1, 'a')")
        await cur.commit()
        for sql, expected in (
            ("INSERT INTO parent VALUES (2, 'a')", exc.UniqueViolation),
            ("INSERT INTO parent VALUES (2, NULL)", exc.NotNullViolation),
            ("INSERT INTO child VALUES (9)", exc.ForeignKeyViolation),
            ("SELECT * FROM missing", exc.ProgrammingError),
            ("SELEC 1", exc.ProgrammingError),
        ):
            with pytest.raises(expected) as raised:
                await cur.execute(sql)
            assert str(raised.value.code).startswith("SQLITE_")
            assert raised.value.constraint is None
            await cur.rollback()
    await db.close()


async def test_busy_database_is_a_conflict(tmp_path):
    uri = f"aiosqlite:///{tmp_path / 'busy.db'}"
    db = AsyncDatabase(uri, timeout=0)
    async with db.cursor as first, db.cursor as second:
        await first.execute("CREATE TABLE t (id INT)")
        await first.commit()
        await first.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(exc.TransactionConflict):
            await second.execute("INSERT INTO t VALUES (2)")
    await db.close()


async def test_closed_connection_raises_quma_exception(tmp_path):
    db = AsyncDatabase(f"aiosqlite:///{tmp_path / 'c.db'}")
    async with db.cursor as cur:
        raw_conn = cur.raw_conn
        assert raw_conn is not None
        await raw_conn.close()
        with pytest.raises(exc.DatabaseError):
            await cur.execute("SELECT 1")
    await db.close()


async def test_executescript(tmp_path):
    db = AsyncDatabase(f"aiosqlite:///{tmp_path / 's.db'}")
    async with db.cursor as cur:
        await cur.executescript(
            "CREATE TABLE t (id INT); INSERT INTO t VALUES (1);"
        )
        assert await cur.query("SELECT id FROM t").value() == 1
        with pytest.raises(exc.DatabaseError):
            await cur.executescript("SELEC 1;")
    await db.close()
