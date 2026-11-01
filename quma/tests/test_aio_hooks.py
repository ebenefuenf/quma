import asyncio
import logging
from types import SimpleNamespace

import pytest

from .. import AsyncDatabase
from .test_aio_transaction import (
    DRIVERS,
    PG_URI,
    prepare,
)

pytestmark = pytest.mark.anyio

# The keyword each driver's execute() has for the parameters.
PARAMS_KEYWORD = {"psycopg": "params", "asyncmy": "args"}


@pytest.fixture(params=DRIVERS)
def uri(request):
    return request.param


@pytest.fixture
async def open_db(uri, named_sqldirs):
    prepare(uri)
    dbs = []

    def create(**kwargs):
        dbs.append(AsyncDatabase(uri, named_sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        await db.close()


@pytest.fixture
def events():
    return []


@pytest.fixture
def db(open_db, events):
    return open_db(on_execute=events.append)


def sleep(uri, seconds):
    if uri.startswith("psycopg"):
        return f"SELECT pg_sleep({seconds})"
    return f"SELECT SLEEP({seconds})"


async def test_script_reports_what_the_driver_received(db, events):
    async with db.cursor as cur:
        rows = await cur.users.by_name(name="User 1").all()
    assert len(rows) == 1
    [event] = events
    assert event.name == "users/by_name"
    assert "name = %(name)s" in event.sql
    assert event.params == {"name": "User 1"}
    assert event.rowcount == 1
    assert event.duration > 0
    assert event.error is None


async def test_statements_outside_scripts_have_no_name(db, events):
    async with db.cursor as cur:
        await cur.query("SELECT 1").all()
        await cur.execute("SELECT 2")
        await cur.fetchall()
        await cur.commit()
    await db.execute("SELECT 3")
    assert [event.name for event in events] == [None, None, None]
    assert [event.sql for event in events] == [
        "SELECT 1",
        "SELECT 2",
        "SELECT 3",
    ]


async def test_executemany(db, events):
    sql = "UPDATE users SET city = 'X' WHERE id = %s"
    params = [(1,), (2,)]
    async with db.cursor as cur:
        await cur.executemany(sql, params)
        await cur.rollback()
    [event] = events
    assert event.sql == sql
    assert event.params == params
    assert event.rowcount == 2


async def test_params_given_by_keyword(db, uri, events):
    keyword = PARAMS_KEYWORD[uri.split(":")[0].removesuffix("+pool")]
    async with db.cursor as cur:
        await cur.execute("SELECT %s", **{keyword: [1]})
        await cur.fetchall()
    [event] = events
    assert event.params == [1]


async def test_failed_statement(db, events):
    async with db.cursor as cur:
        with pytest.raises(Exception, match="missing") as raised:
            await cur.query("SELECT * FROM missing").all()
        await cur.rollback()
    [event] = events
    assert event.error is raised.value
    assert event.rowcount is None


async def test_duration_covers_the_statement(db, uri, events):
    async with db.cursor as cur:
        await cur.query(sleep(uri, 0.05)).all()
    assert events[0].duration >= 0.04


async def test_duration_leaves_out_waiting_for_the_connection(db, uri, events):
    carrier = SimpleNamespace()
    async with db(carrier).cursor as first, db(carrier).cursor as second:
        slow = asyncio.create_task(first.execute(sleep(uri, 0.3)))
        await asyncio.sleep(0.05)
        await second.executemany(
            "UPDATE users SET city = 'X' WHERE id = %s", [(1,)]
        )
        await slow
        await second.rollback()
    await db.release(carrier)
    updated = next(event for event in events if "UPDATE" in event.sql)
    assert updated.duration < 0.15


async def test_cancelled_statement(db, uri, events):
    async with db.cursor as cur:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(cur.query(sleep(uri, 1)).run(), 0.05)
    [event] = events
    assert isinstance(event.error, asyncio.CancelledError)


async def test_failing_hook_keeps_the_result(open_db, caplog):
    def hook(event):
        raise ValueError("bug in the hook")

    db = open_db(on_execute=hook)
    async with db.cursor as cur:
        assert len(await cur.users.by_name(name="User 1").all()) == 1
    assert "users/by_name" in caplog.text
    assert "bug in the hook" in caplog.text


async def test_failing_hook_keeps_the_statements_error(open_db):
    def hook(event):
        raise ValueError("bug in the hook")

    db = open_db(on_execute=hook)
    async with db.cursor as cur:
        with pytest.raises(Exception, match="missing"):
            await cur.query("SELECT * FROM missing").all()
        await cur.rollback()


async def test_transaction_control_isnt_reported(db, events):
    async with db.cursor as cur:
        async with cur.transaction():
            await cur.users.remove(name="User 1").run()
            async with cur.transaction():
                await cur.users.remove(name="User 2").run()
    assert [event.name for event in events] == ["users/remove"] * 2


async def test_stream_reports_its_opening_only(db, uri, events):
    async with db.cursor as cur:
        rows = [row async for row in cur.users.all().stream(2)]
    assert len(rows) == 7
    [event] = events
    assert event.name == "users/all"
    assert event.rowcount is None
    assert event.sql.startswith("DECLARE") == uri.startswith("psycopg")


async def test_stream_that_fails_to_open(db, events):
    async with db.cursor as cur:
        with pytest.raises(Exception, match="missing") as raised:
            async for _row in cur.query("SELECT * FROM missing").stream():
                pass
        await cur.rollback()
    [event] = events
    assert event.error is raised.value


async def test_debug_log(open_db, caplog):
    db = open_db()
    with caplog.at_level(logging.DEBUG, logger="quma"):
        async with db.cursor as cur:
            await cur.users.by_name(name="User 1").all()
    records = [r for r in caplog.records if r.name == "quma"]
    assert len(records) == 1
    message = records[0].getMessage()
    assert message.startswith("users/by_name: ")
    assert " ms, rowcount 1\n" in message
    assert "User 1" not in message


def test_coroutine_function_is_rejected():
    async def hook(event):
        pass

    with pytest.raises(TypeError, match="plain function"):
        AsyncDatabase(PG_URI, on_execute=hook)  # ty: ignore[invalid-argument-type]
