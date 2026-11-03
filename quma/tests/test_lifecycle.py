"""What a cursor and its connection do in every state: opened twice, used after
closing, after the server dropped the connection. Each driver has its own way
to fail here, and a slot lost in a pool only shows on a later checkout."""

import sqlite3
import time
from typing import Any

import pytest

from .. import Database, exc
from . import util

SQL = "SELECT 1 AS a"
CONNECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "plain": ("", {}),
    "persist": ("", {"persist": True}),
    "pool": ("+pool", {"size": 1, "overflow": 1, "timeout": 0.2}),
}


@pytest.fixture(
    params=[
        "sqlite3",
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ]
)
def driver(request, tmp_path):
    name = request.param
    pytest.importorskip("MySQLdb" if name == "mysqlclient" else name)
    if name == "sqlite3":
        return f"sqlite3:///{tmp_path / 'lifecycle.sqlite'}"
    if name == "mysqlclient":
        return util.MYSQL_URI
    return util.pg_uri(name)


@pytest.fixture(params=CONNECTIONS)
def database(request, driver):
    suffix, options = CONNECTIONS[request.param]
    scheme, rest = driver.split("://", 1)
    db = Database(f"{scheme}{suffix}://{rest}", **options)
    yield db
    db.close()


def lose(raw):
    if isinstance(raw, sqlite3.Connection):
        raw.close()
        return
    if hasattr(raw, "thread_id"):
        uri, kill = util.MYSQL_URI, f"KILL {raw.thread_id()}"
    else:
        pid = raw.info.backend_pid
        uri = util.pg_uri("psycopg")
        kill = f"SELECT pg_terminate_backend({pid}, 5000)"
    killer = Database(uri)
    with killer.cursor as cur:
        cur.execute(kill)
    killer.close()
    # MySQL's KILL returns before the connection is gone.
    time.sleep(0.05)


def assert_no_slot_lost(db):
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1


def with_and_with(db):
    with db.cursor as cur:
        with cur:
            pass


def called_and_with(db):
    with db.cursor() as cur:
        with cur:
            pass


def called_twice(db):
    cur = db.cursor()
    try:
        cur()
    finally:
        cur.close()


def created_twice(db):
    cur = db.cursor
    cur.create_cursor()
    try:
        cur.create_cursor()
    finally:
        cur.close()


def with_and_created(db):
    with db.cursor as cur:
        cur.create_cursor()


def carried_with_and_with(db):
    carrier = object()
    try:
        with db(carrier).cursor as cur:
            with cur:
                pass
    finally:
        db.release(carrier)


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
def test_an_open_cursor_refuses_to_open(database, open_twice):
    with pytest.raises(exc.APIError, match="already open"):
        open_twice(database)
    assert_no_slot_lost(database)


def test_a_closed_cursor_opens_again(database):
    cur = database.cursor
    for _ in range(2):
        with cur:
            assert cur.query(SQL).value() == 1
    cur.create_cursor()
    cur.close()
    with cur:
        assert cur.query(SQL).value() == 1
    assert_no_slot_lost(database)


USES = {
    "query": lambda cur: cur.query(SQL).all(),
    "execute": lambda cur: cur.execute(SQL),
    "fetchall": lambda cur: cur.fetchall(),
    "fetchone": lambda cur: cur.fetchone(),
    "mogrify": lambda cur: cur.mogrify(SQL, {}),
    "commit": lambda cur: cur.commit(),
    "rollback": lambda cur: cur.rollback(),
    "block": lambda cur: cur.transaction().__enter__(),
}


@pytest.mark.parametrize("use", USES.values(), ids=USES.keys())
def test_a_cursor_without_a_connection_says_so(database, use):
    cur = database.cursor
    with pytest.raises(exc.APIError, match="no open connection"):
        use(cur)
    with cur:
        cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        use(cur)
    assert_no_slot_lost(database)


@pytest.mark.parametrize("use", ["query", "execute", "fetchall", "mogrify"])
def test_a_closed_carried_cursor_says_so(database, use):
    carrier = object()
    with database(carrier).cursor as cur:
        cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        USES[use](cur)
    database.release(carrier)
    assert_no_slot_lost(database)


def test_a_closed_carried_cursor_can_still_commit(database):
    carrier = object()
    with database(carrier).cursor as cur:
        cur.execute(SQL)
    cur.commit()
    database.release(carrier)
    assert_no_slot_lost(database)


def test_mogrify_binds_the_values(driver):
    placeholder = "?" if driver.startswith("sqlite3") else "%(v)s"
    db = Database(driver)
    with db.cursor as cur:
        cur.execute(SQL)
        bound = cur.mogrify(f"SELECT {placeholder}", {"v": 7})
    assert bound == ("SELECT ?" if placeholder == "?" else "SELECT 7")


def query(cur):
    return cur.query(SQL).all()


def execute(cur):
    return cur.execute(SQL)


def stream(cur):
    return next(iter(cur.query(SQL).stream()))


def block(cur):
    with cur.transaction():
        cur.query(SQL).all()


@pytest.mark.parametrize("use", [query, execute, stream, block])
def test_a_lost_connection_raises_connection_lost(database, use):
    with database.cursor as cur:
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
    assert_recovers(database)


def assert_recovers(db):
    """A connection found broken only on its next use costs one statement."""
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    try:
        with db.cursor as cur:
            cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1


@pytest.mark.parametrize(
    "use", [lambda cur: cur.commit(), lambda cur: cur.rollback()]
)
def test_ending_a_transaction_on_a_lost_connection(database, use):
    with database.cursor as cur:
        cur.execute(SQL)
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
    assert_recovers(database)


def test_a_block_after_a_failed_statement_on_a_lost_connection(database):
    with database.cursor as cur:
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            cur.query(SQL).all()
        with pytest.raises(exc.ConnectionLost):
            with cur.transaction():
                cur.query(SQL).all()
    assert_recovers(database)


def test_a_lost_connection_keeps_the_exception_of_the_block(database):
    with pytest.raises(ZeroDivisionError):
        with database.cursor as cur:
            lose(cur.raw_conn)
            raise ZeroDivisionError
    assert_recovers(database)


@pytest.fixture(params=["persist", "pool"])
def keeping(request, driver):
    suffix, options = CONNECTIONS[request.param]
    scheme, rest = driver.split("://", 1)
    db = Database(f"{scheme}{suffix}://{rest}", **options)
    yield db
    db.close()


def test_a_connection_lost_between_cursors(keeping):
    with keeping.cursor as cur:
        cur.execute(SQL)
        raw = cur.raw_conn
    lose(raw)
    assert_recovers(keeping)


def test_an_autocommit_cursor_after_a_lost_connection(keeping):
    with keeping.cursor as cur:
        cur.execute(SQL)
        raw = cur.raw_conn
    lose(raw)
    try:
        with keeping.cursor(autocommit=True) as cur:
            cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    assert_recovers(keeping)


def test_closing_a_database_with_a_lost_connection(database):
    with database.cursor as cur:
        raw = cur.raw_conn
        lose(raw)
        with pytest.raises(exc.ConnectionLost):
            cur.query(SQL).all()
    database.close()


def test_closing_a_database_while_a_cursor_is_open(database):
    cur = database.cursor
    cur.create_cursor()
    database.close()
    cur.close()


def test_a_closed_persistent_connection_stays_closed(driver):
    db = Database(driver, persist=True)
    cur = db.cursor
    db.close()
    with pytest.raises(exc.APIError, match="closed"):
        cur.create_cursor()


def test_pessimistic_finds_a_connection_closed_by_hand(driver):
    db = Database(driver, persist=True, pessimistic=True)
    with db.cursor as cur:
        raw: Any = cur.raw_conn
    raw.close()
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1
    db.close()
