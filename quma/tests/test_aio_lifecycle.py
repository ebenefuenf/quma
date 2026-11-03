"""The async side of test_lifecycle.py."""

import asyncio
from contextlib import aclosing
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


COPY = "COPY (SELECT generate_series(1, 100000)) TO STDOUT"
MANY_ROWS = "SELECT generate_series(1, 100000) AS n"


@pytest.fixture(params=["plain", "persist", "pool"])
async def psycopg_db(request):
    suffix, options = CONNECTIONS[request.param]
    db = AsyncDatabase(util.pg_uri(f"psycopg{suffix}"), **options)
    yield db
    await db.close()


async def within_seconds(awaitable):
    return await asyncio.wait_for(awaitable, 5)


async def kept_stream(cur):
    stream = cur.stream(MANY_ROWS)
    assert (await anext(stream))[0] == 1
    return stream


@pytest.mark.postgres
@pytest.mark.parametrize(
    "use",
    [
        lambda cur: cur.query(SQL).all(),
        lambda cur: cur.execute(SQL),
        lambda cur: cur.commit(),
        lambda cur: cur.rollback(),
        lambda cur: cur.transaction().__aenter__(),
        lambda cur: anext(cur.stream(MANY_ROWS)),
        lambda cur: anext(aiter(cur.query(SQL).stream())),
    ],
)
async def test_a_kept_driver_stream_refuses_other_statements(psycopg_db, use):
    async def run():
        async with psycopg_db.cursor as cur:
            stream = await kept_stream(cur)
            with pytest.raises(exc.APIError, match="holds this connection"):
                await use(cur)
            assert (await anext(stream))[0] == 2

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "leave",
    [
        lambda cur: cur.__aexit__(None, None, None),
        lambda cur: cur.close(),
        lambda cur: cur.put(),
    ],
)
async def test_closing_a_cursor_ends_its_driver_stream(psycopg_db, leave):
    async def run():
        cur = psycopg_db.cursor
        await cur.__aenter__()
        stream = await kept_stream(cur)
        await leave(cur)
        with pytest.raises(exc.APIError, match="closed before its end"):
            await anext(stream)

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
async def test_releasing_a_carrier_ends_a_driver_stream(psycopg_db):
    async def run():
        carrier = object()
        cur = psycopg_db(carrier).cursor
        await cur.create_cursor()
        await kept_stream(cur)
        await psycopg_db.release(carrier)

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
async def test_closing_a_database_ends_a_driver_stream(psycopg_db):
    async def run():
        cur = psycopg_db.cursor
        await cur.create_cursor()
        await kept_stream(cur)
        await psycopg_db.close()
        await cur.close()

    await within_seconds(run())


@pytest.mark.postgres
async def test_aclosing_a_driver_stream_frees_the_connection(psycopg_db):
    async def run():
        async with psycopg_db.cursor as cur:
            async with aclosing(cur.stream(MANY_ROWS)) as stream:
                async for _ in stream:
                    break
            # psycopg cancels the query, which aborts the transaction.
            await cur.rollback()
            assert await cur.query(SQL).value() == 1

    await within_seconds(run())


@pytest.mark.postgres
async def test_a_finished_driver_stream_frees_the_connection(psycopg_db):
    async with psycopg_db.cursor as cur:
        rows = [row[0] async for row in cur.stream("SELECT 1 UNION SELECT 2")]
        assert rows == [1, 2]
        assert await cur.query(SQL).value() == 1
    await assert_no_slot_lost(psycopg_db)


@pytest.mark.postgres
async def test_a_driver_stream_raises_quma_errors(psycopg_db):
    async with psycopg_db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            await anext(cur.stream("SELECT nope"))
        await cur.rollback()
    await assert_no_slot_lost(psycopg_db)


@pytest.mark.postgres
async def test_another_task_closing_the_cursor_waits_for_a_copy(psycopg_db):
    cur = psycopg_db.cursor
    await cur.create_cursor()
    async with cur.copy(COPY) as copy:
        assert await copy.read()
        closing = asyncio.create_task(cur.close())
        await asyncio.sleep(0.05)
        assert not closing.done()
        while await copy.read():
            pass
    await within_seconds(closing)
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "use",
    [
        lambda cur: cur.query(SQL).all(),
        lambda cur: cur.commit(),
        lambda cur: cur.copy(COPY).__aenter__(),
    ],
)
async def test_a_copy_refuses_other_statements(psycopg_db, use):
    async def run():
        async with psycopg_db.cursor as cur:
            async with cur.copy(COPY) as copy:
                assert await copy.read()
                with pytest.raises(exc.APIError, match="busy"):
                    await use(cur)

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
async def test_closing_a_cursor_inside_a_copy_ends_it(psycopg_db):
    async def run():
        cur = psycopg_db.cursor
        await cur.create_cursor()
        async with cur.copy(COPY) as copy:
            assert await copy.read()
            await cur.close()

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
async def test_a_copy_left_open_ends_with_its_cursor(psycopg_db):
    async def run():
        async with psycopg_db.cursor as cur:
            copy = await cur.copy(COPY).__aenter__()
            await copy.read()

    await within_seconds(run())
    await within_seconds(assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
async def test_a_copy_still_copies(psycopg_db):
    async with psycopg_db.cursor as cur:
        await cur.execute("CREATE TEMPORARY TABLE lifecycle_copy (a INT)")
        async with cur.copy("COPY lifecycle_copy FROM STDIN") as copy:
            await copy.write_row((7,))
        assert await cur.query("SELECT a FROM lifecycle_copy").value() == 7
        await cur.rollback()
    await assert_no_slot_lost(psycopg_db)


MISTAKES = {
    "missing name": ("SELECT %(a)s AS a", ":a", {"b": 1}),
    "no names": ("SELECT %(a)s AS a", ":a", {}),
    "too few": ("SELECT %s AS a, %s AS b", "?, ?", (1,)),
    "too many": ("SELECT %s AS a", "?", (1, 2)),
    "list for a name": ("SELECT %(a)s AS a", ":a", (1,)),
    "name for a position": ("SELECT %s AS a", "?", {"a": 1}),
    "no sequence": ("SELECT %s AS a", "?", 5),
    "bad format": ("SELECT %d AS a", "?", ("x",)),
    "unknown format": ("SELECT %y AS a", "?", (1,)),
    "incomplete name": ("SELECT %(a) AS a", "?", {"a": 1}),
    "lone percent": ("SELECT 1 % AS a", "?", {"a": 1}),
}


def sql_of(driver, pyformat, qmark):
    if driver.startswith("aiosqlite"):
        return f"SELECT {qmark}"
    return pyformat


@pytest.mark.filterwarnings("ignore:Binding 1:DeprecationWarning")
@pytest.mark.parametrize("mistake", MISTAKES.values(), ids=MISTAKES.keys())
async def test_a_mistake_in_parameters_is_quma_error(
    database, driver, mistake
):
    pyformat, qmark, params = mistake
    async with database.cursor as cur:
        try:
            await cur.execute(sql_of(driver, pyformat, qmark), params)
        except exc.DatabaseError:
            pass
    await assert_no_slot_lost(database)


@pytest.mark.parametrize("params", [{"b": 1}, {}], ids=["other", "none"])
async def test_a_missing_name_raises_programming_error(driver, params):
    db = AsyncDatabase(driver)
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError, match="a"):
            await cur.query("SELECT :a AS a", **params).all()
        with pytest.raises(exc.ProgrammingError, match="a"):
            await anext(aiter(cur.query("SELECT :a AS a", **params).stream()))
    await db.close()


async def test_a_missing_name_is_a_key_error_too(driver):
    db = AsyncDatabase(driver)
    async with db.cursor as cur:
        with pytest.raises(KeyError) as info:
            await cur.query("SELECT :wanted AS a").all()
    assert isinstance(info.value, exc.MissingParameter)
    assert isinstance(info.value, exc.ProgrammingError)
    assert "wanted" in str(info.value)
    assert not str(info.value).startswith("'")
    await db.close()


async def test_a_missing_name_says_which(driver):
    if driver.startswith("aiosqlite"):
        pytest.skip("Says it its own way, in a message of sqlite3.")
    db = AsyncDatabase(driver)
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError, match="missing: wanted"):
            await cur.query("SELECT :wanted AS a").all()
    await db.close()


async def test_positional_mistakes_in_native_mode(driver):
    db = AsyncDatabase(driver, placeholders="native")
    too_few = sql_of(driver, "SELECT %s AS a, %s AS b", "?, ?")
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            await cur.query(too_few, 1).all()
    await db.close()


async def test_echo_keeps_the_error_of_a_statement(driver, capsys):
    db = AsyncDatabase(driver, echo=True)
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            await cur.query("SELECT :a AS a").all()
    assert "SELECT" in capsys.readouterr().out
    await db.close()
