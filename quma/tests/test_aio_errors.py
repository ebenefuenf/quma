import asyncio

import pytest

from .. import (
    AsyncDatabase,
    exc,
)
from . import util
from .test_aio_transaction import (
    DRIVERS,
    MY_URI,
    PG_URI,
    prepare,
)

pytestmark = pytest.mark.anyio

# test_aio_sqlite.py covers aiosqlite: its errors have no constraint names.
DRIVERS = [driver for driver in DRIVERS if "aiosqlite" not in str(driver.id)]

BASE = [
    pytest.param(PG_URI, id="psycopg", marks=pytest.mark.postgres),
    pytest.param(MY_URI, id="asyncmy", marks=pytest.mark.mysql),
]
POSTGRES = [pytest.param(PG_URI, id="psycopg", marks=pytest.mark.postgres)]
MYSQL = [pytest.param(MY_URI, id="asyncmy", marks=pytest.mark.mysql)]

TABLES = (
    "DROP TABLE IF EXISTS err_child",
    "DROP TABLE IF EXISTS err_parent",
    """CREATE TABLE err_parent (
        id INT PRIMARY KEY,
        name VARCHAR(40) NOT NULL,
        short VARCHAR(2),
        age INT,
        CONSTRAINT uq_err_name UNIQUE (name),
        CONSTRAINT ck_err_age CHECK (age > 0))""",
    """CREATE TABLE err_child (
        id INT PRIMARY KEY,
        parent INT,
        CONSTRAINT fk_err_parent FOREIGN KEY (parent)
            REFERENCES err_parent (id))""",
    "INSERT INTO err_parent (id, name, age) VALUES (1, 'a', 1), (2, 'b', 2)",
    "INSERT INTO err_child (id, parent) VALUES (1, 1)",
)


@pytest.fixture(params=DRIVERS)
def uri(request):
    return request.param


@pytest.fixture
async def open_db(uri, named_sqldirs):
    prepare(uri)
    dbs = []

    def create(**kwargs):
        kwargs.setdefault("sqldirs", named_sqldirs)
        dbs.append(AsyncDatabase(uri, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        await db.close()


@pytest.fixture
async def db(open_db):
    db = open_db()
    async with db.cursor as cur:
        for statement in TABLES:
            await cur.execute(statement)
        await cur.commit()
    yield db
    async with db.cursor as cur:
        await cur.execute("DROP TABLE err_child")
        await cur.execute("DROP TABLE err_parent")
        await cur.commit()


async def failure(db, sql):
    async with db.cursor as cur:
        with pytest.raises(exc.DatabaseError) as raised:
            await cur.execute(sql)
        await cur.rollback()
    return raised.value


def is_postgres(uri):
    return uri.startswith("psycopg")


@pytest.mark.parametrize(
    "sql, expected, constraint",
    [
        (
            "INSERT INTO err_parent (id, name) VALUES (3, 'a')",
            exc.UniqueViolation,
            "uq_err_name",
        ),
        (
            "INSERT INTO err_child (id, parent) VALUES (2, 99)",
            exc.ForeignKeyViolation,
            "fk_err_parent",
        ),
        (
            "DELETE FROM err_parent WHERE id = 1",
            exc.ForeignKeyViolation,
            "fk_err_parent",
        ),
        (
            "INSERT INTO err_parent (id, name, age) VALUES (3, 'z', -1)",
            exc.CheckViolation,
            "ck_err_age",
        ),
    ],
    ids=["unique", "foreign_key_insert", "foreign_key_delete", "check"],
)
async def test_constraint_violations(db, sql, expected, constraint):
    error = await failure(db, sql)
    assert type(error) is expected
    assert error.constraint == constraint
    assert isinstance(error.__cause__, db.conn.driver_error)
    assert not isinstance(error, db.conn.driver_error)


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO err_parent (id, name) VALUES (3, NULL)",
        "INSERT INTO err_parent (id) VALUES (3)",
    ],
    ids=["null", "no_value"],
)
async def test_not_null_violation(db, sql):
    assert type(await failure(db, sql)) is exc.NotNullViolation


@pytest.mark.parametrize(
    "sql",
    ["SELEC 1", "SELECT * FROM err_missing", "SELECT nope FROM err_parent"],
    ids=["syntax", "table", "column"],
)
async def test_statement_that_cant_run(db, sql):
    assert type(await failure(db, sql)) is exc.ProgrammingError


async def test_value_too_long(db):
    sql = "INSERT INTO err_parent (id, name, short) VALUES (3, 'z', 'long')"
    assert type(await failure(db, sql)) is exc.DataError


async def test_script_name(db):
    values = {"id": 1, "name": "User 1", "email": "x", "city": "y"}
    async with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation) as raised:
            await cur.users.add(**values).run()
        await cur.rollback()
    assert raised.value.script == "users/add"


async def test_executemany(db):
    async with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation):
            await cur.executemany(
                "INSERT INTO err_parent (id, name) VALUES (%s, 'z')",
                [(5,), (6,)],
            )
        await cur.rollback()


@pytest.mark.parametrize("uri", MYSQL)
async def test_callproc(db):
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            await cur.callproc("err_missing")
        await cur.rollback()


async def test_db_execute(db):
    with pytest.raises(exc.UniqueViolation):
        await db.execute("INSERT INTO err_parent (id, name) VALUES (1, 'z')")


@pytest.mark.parametrize("uri", BASE)
async def test_deadlock(db):
    first_locked = asyncio.Event()
    second_locked = asyncio.Event()
    errors = []

    async def lock(first, second, mine, other):
        async with db.cursor as cur:
            try:
                await cur.execute(
                    f"UPDATE err_parent SET age = 5 WHERE id = {first}"
                )
                mine.set()
                await other.wait()
                await cur.execute(
                    f"UPDATE err_parent SET age = 5 WHERE id = {second}"
                )
            except exc.DatabaseError as e:
                errors.append(e)
            await cur.rollback()

    await asyncio.gather(
        lock(1, 2, first_locked, second_locked),
        lock(2, 1, second_locked, first_locked),
    )
    assert [type(error) for error in errors] == [exc.TransactionConflict]


@pytest.mark.parametrize("uri", BASE)
async def test_lock_wait_timeout(db, uri):
    setting = (
        "SET lock_timeout = '50ms'"
        if is_postgres(uri)
        else "SET SESSION innodb_lock_wait_timeout = 1"
    )
    async with db.cursor as holder:
        await holder.execute("UPDATE err_parent SET age = 5 WHERE id = 1")
        async with db.cursor as cur:
            await cur.execute(setting)
            with pytest.raises(exc.TransactionConflict):
                await cur.execute("UPDATE err_parent SET age = 6 WHERE id = 1")
            await cur.rollback()
        await holder.rollback()


async def deferred_violation(cur):
    await cur.execute(
        "CREATE TEMP TABLE err_d (id INT, CONSTRAINT uq_err_d UNIQUE (id) "
        "DEFERRABLE INITIALLY DEFERRED)"
    )
    await cur.execute("INSERT INTO err_d VALUES (1), (1)")


@pytest.mark.parametrize("uri", POSTGRES)
async def test_commit(open_db):
    db = open_db()
    async with db.cursor as cur:
        await deferred_violation(cur)
        with pytest.raises(exc.UniqueViolation):
            await cur.commit()
        await cur.rollback()


@pytest.mark.parametrize("uri", POSTGRES)
async def test_commit_of_a_contextcommit_block(open_db):
    db = open_db(contextcommit=True)
    with pytest.raises(exc.UniqueViolation):
        async with db.cursor as cur:
            await deferred_violation(cur)


@pytest.mark.parametrize("uri", POSTGRES)
@pytest.mark.parametrize("autocommit", [False, True])
async def test_commit_of_a_transaction_block(open_db, autocommit):
    db = open_db(autocommit=autocommit)
    async with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation):
            async with cur.transaction():
                await deferred_violation(cur)


async def test_statement_in_a_block(db):
    async with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation):
            async with cur.transaction():
                await cur.query(
                    "INSERT INTO err_parent (id, name) VALUES (1, 'z')"
                ).run()


@pytest.mark.parametrize("uri", POSTGRES)
async def test_postgres_stream(db):
    sql = "SELECT 1 / (3 - g) FROM generate_series(1, 5) g"
    rows = []
    async with db.cursor as cur:
        with pytest.raises(exc.DataError):
            async for row in cur.query(sql).stream(1):
                rows.append(row[0])
        await cur.rollback()
    assert rows == [0, 1]


@pytest.mark.parametrize("uri", MYSQL)
async def test_mysql_stream(db):
    async with db.cursor as cur:
        await cur.execute("DROP FUNCTION IF EXISTS err_late_a")
        await cur.execute(
            "CREATE FUNCTION err_late_a(x INT) RETURNS INT DETERMINISTIC "
            "NO SQL BEGIN IF x = 3 THEN SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'late'; END IF; RETURN x; END"
        )
    rows = []
    # Fails instead of hanging: asyncmy waits for rows that never come.
    async with asyncio.timeout(10):
        async with db.cursor as cur:
            query = cur.query("SELECT err_late_a(id) FROM users ORDER BY id")
            with pytest.raises(exc.RaisedError, match="late"):
                async for row in query.stream(1):
                    rows.append(row[0])
            assert await cur.query("SELECT 42 AS answer").value() == 42
    async with db.cursor as cur:
        await cur.execute("DROP FUNCTION err_late_a")
    assert rows == [1, 2]


async def test_stream_that_fails_to_open(db):
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            async for _row in cur.query("SELECT * FROM err_missing").stream():
                pass
        await cur.rollback()


async def test_hook_sees_the_same_error(open_db):
    events = []
    db = open_db(on_execute=events.append)
    async with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError) as raised:
            await cur.query("SELECT * FROM err_missing").all()
        await cur.rollback()
    assert events[0].error is raised.value


@pytest.mark.parametrize("uri", MYSQL)
async def test_mysql_duplicate_value_cant_fake_the_constraint(db):
    value = "x' for key 'evil"
    sql = "INSERT INTO err_parent (id, name) VALUES (:id, :name)"
    async with db.cursor as cur:
        await cur.query(sql, id=3, name=value).run()
        with pytest.raises(exc.UniqueViolation) as raised:
            await cur.query(sql, id=4, name=value).run()
        await cur.rollback()
    assert raised.value.constraint == "uq_err_name"
    assert str(raised.value).startswith("Duplicate entry")


@pytest.mark.parametrize("uri", POSTGRES)
async def test_driver_details_through_the_cause(db):
    error = await failure(
        db, "INSERT INTO err_parent (id, name) VALUES (3, 'a')"
    )
    assert error.__cause__.diag.table_name == "err_parent"


@pytest.mark.parametrize("autocommit", [False, True])
@pytest.mark.postgres
async def test_cursor_on_a_closed_connection(autocommit):
    db = AsyncDatabase(util.pg_uri("psycopg+pool"), size=1, overflow=0)
    async with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    await raw_conn.close()
    with pytest.raises(exc.DatabaseError):
        async with db.cursor(autocommit=autocommit):
            pass
    await db.close()


def wrong_port(uri):
    if is_postgres(uri):
        return uri.replace(f":{util.PGSQL_PORT}/", ":1/")
    return uri.replace(f":{util.MYSQL_PORT}/", ":1/")


@pytest.mark.parametrize("uri", BASE)
async def test_failing_connection(uri):
    db = AsyncDatabase(wrong_port(uri))
    with pytest.raises(exc.ConnectionError) as raised:
        async with db.cursor:
            pass
    assert not isinstance(raised.value, exc.ConnectionLost)
    assert raised.value.__cause__ is not None
    await db.close()
