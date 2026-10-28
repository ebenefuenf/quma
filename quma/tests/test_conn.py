import queue
import sqlite3
import threading
from unittest.mock import Mock

import pytest

from .. import (
    Database,
    conn,
    connect,
    exc,
)
from ..pool import Pool
from . import util


def connect_pool(uri, **kwargs):
    pool = connect(uri, **kwargs)
    assert isinstance(pool, Pool)
    return pool


def connect_single(uri, **kwargs):
    single = connect(uri, **kwargs)
    assert isinstance(single, conn.Connection)
    return single


def get_cursor_mock(exception):
    def cursor():
        m = Mock()
        m.execute = Mock()
        m.execute.side_effect = exception
        return m

    return cursor


def test_base_connection(pgdburl):
    # We test with a PostgreSQL url but any other would do
    kwargs = dict(persist=True)
    cn = conn.Connection(pgdburl, kwargs)
    assert kwargs.get("persist") is None
    assert cn.database == util.PGSQL_DB
    assert cn.username == util.PGSQL_USER
    assert cn.password == util.PGSQL_PASS
    assert cn.url == pgdburl
    c = Mock()
    cn.conn = c
    with pytest.raises(NotImplementedError):
        cn.check()
    cn.close()
    cn.close(c)
    assert c.close.call_count == 2


def test_failing_check():
    conn = connect_single(util.SQLITE_MEMORY, persist=True, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(sqlite3.ProgrammingError)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)
    connmock.cursor = get_cursor_mock(sqlite3.OperationalError)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)
    conn.close()


def test_persistent_pessimistic(dbpess):
    with dbpess.cursor as cursor:
        cn = cursor.raw_conn
    with dbpess.cursor as cursor:
        assert cn is cursor.raw_conn
    dbpess.conn._check = Mock()
    dbpess.conn._check.side_effect = exc.OperationalError
    with dbpess.cursor as cursor:
        assert cn is not cursor.raw_conn
    with pytest.raises(sqlite3.ProgrammingError):
        cn.execute("SELECT 1")


def pool_overflow_counting(uri):
    conn = connect_pool(uri, size=1, overflow=4)
    cn1 = conn.get()
    cn2 = conn.get()
    cn3 = conn.get()
    assert conn.overflow == 2
    conn.put(cn1)
    # Queue not full yet, overflow does not decrease
    assert conn.overflow == 2
    conn.put(cn2)
    # Queue is full now, overflow must be lower
    assert conn.overflow == 1
    cn4 = conn.get()
    cn5 = conn.get()
    assert conn.overflow == 2
    conn._conn.get = Mock()
    conn._conn.get.side_effect = ValueError
    with pytest.raises(ValueError):
        conn.get()
    assert conn.overflow == 2
    for cn in (cn3, cn4, cn5):
        conn.put(cn)
    conn.close()


@pytest.mark.postgres
def test_postgres_pool_overflow_counting(pgdriver):
    pool_overflow_counting(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pool_overflow_counting():
    pool_overflow_counting(util.MYSQL_POOL_URI)


def non_persistent(uri, connection, pessimistic):
    conn = connect_single(uri, pessimistic=pessimistic)
    cn1 = conn.get()
    assert cn1.closed == 0
    with pytest.raises(AttributeError):
        conn.conn
    assert type(cn1) is connection
    cn2 = conn.get()
    assert cn1 != cn2
    conn.put(cn1)
    assert cn1.closed == 1
    assert cn2.closed == 0
    conn.put(cn2)
    assert cn2.closed == 1
    conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_non_persistent(pgdriver, pessimistic):
    non_persistent(pgdriver.uri, pgdriver.connection, pessimistic)


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_non_persistent(pessimistic):
    from MySQLdb.connections import Connection

    non_persistent(util.MYSQL_URI, Connection, pessimistic)


def persistent(uri, connection):
    conn = connect_single(uri, persist=True)
    cn1 = conn.get()
    assert cn1.closed == 0
    assert conn.conn == cn1
    assert type(cn1) is connection
    conn.put(cn1)
    assert cn1.closed == 0
    cn2 = conn.get()
    assert cn1 == cn2
    assert conn.conn is not None
    conn.close()
    assert cn1.closed == 1
    assert cn2.closed == 1
    with pytest.raises(AttributeError):
        conn.conn
    conn.close()


@pytest.mark.postgres
def test_postgres_persistent(pgdriver):
    persistent(pgdriver.uri, pgdriver.connection)


@pytest.mark.postgres
@pytest.mark.parametrize("scheme", ["postgresql", "postgresql+pool"])
def test_postgresql_scheme_uses_psycopg2(scheme):
    from psycopg2.extensions import connection

    conn = connect(util.pg_uri(scheme))
    raw_conn = conn.get()
    assert type(raw_conn) is connection
    conn.put(raw_conn)
    conn.close()


@pytest.mark.mysql
def test_mysql_persistent():
    from MySQLdb.connections import Connection

    persistent(util.MYSQL_URI, Connection)


def pool(uri, pessimistic, connection):
    from .. import pool

    conn = connect(uri, pessimistic=pessimistic)
    assert type(conn) is pool.Pool
    assert conn.size == 5
    cn1 = conn.get()
    assert conn.overflow == -4
    cn2 = conn.get()
    assert conn.overflow == -3
    assert type(cn1) is connection
    assert type(cn2) is connection
    assert cn1 != cn2
    conn.put(cn1)
    conn.put(cn2)
    assert conn.status().startswith("Pool size: 5 Connections")
    assert conn.checkedin == 2
    cn3 = conn.get()
    assert conn.checkedin == 1
    assert cn3 == cn1
    conn.put(cn3)
    conn.close()
    assert conn.checkedin == 0


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_pool(pgdriver, pessimistic):
    pool(pgdriver.pool_uri, pessimistic, pgdriver.connection)


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_pool(pessimistic):
    from MySQLdb.connections import Connection

    pool(util.MYSQL_POOL_URI, pessimistic, Connection)


def pessimistic_failure(uri):
    conn = connect_pool(uri, size=1, overflow=-1, pessimistic=True)
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 == c2
    conn.put(c2)
    conn._conn.check = Mock()
    conn._conn.check.side_effect = exc.OperationalError
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 != c2
    conn.put(c2)
    conn.close()


def test_pool_overflow_race(monkeypatch):
    conn = connect_pool(
        f"sqlite+pool:///{util.SQLITE_FILE}", size=1, overflow=0, timeout=0.01
    )

    def lose_race():
        # Another thread takes the last connection first.
        conn._overflow += 1

    monkeypatch.setattr(conn, "_inc_overflow", lose_race)
    with pytest.raises(exc.TimeoutError):
        conn.get()


def pool_reuse_autocommit(uri, pessimistic, is_autocommit):
    conn = connect(uri, size=1, pessimistic=pessimistic)
    for autocommit in (False, True, False):
        raw_conn = conn.get(autocommit=autocommit)
        assert is_autocommit(raw_conn) is autocommit
        conn.put(raw_conn)
    conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_pool_reuse_autocommit(pgdriver, pessimistic):
    pool_reuse_autocommit(
        pgdriver.pool_uri, pessimistic, lambda conn: conn.autocommit
    )


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_pool_reuse_autocommit(pessimistic):
    pool_reuse_autocommit(
        util.MYSQL_POOL_URI, pessimistic, lambda conn: conn.get_autocommit()
    )


def persistent_pessimistic_autocommit(uri, is_autocommit):
    db = Database(uri, persist=True, pessimistic=True)
    for autocommit in (False, True, False):
        with db(autocommit=autocommit).cursor as cursor:
            assert is_autocommit(cursor.raw_conn) is autocommit
    db.close()


@pytest.mark.postgres
def test_postgres_persistent_pessimistic_autocommit(pgdriver):
    persistent_pessimistic_autocommit(
        pgdriver.uri, lambda conn: conn.autocommit
    )


@pytest.mark.mysql
def test_mysql_persistent_pessimistic_autocommit():
    persistent_pessimistic_autocommit(
        util.MYSQL_URI, lambda conn: conn.get_autocommit()
    )


@pytest.mark.postgres
def test_postgres_pessimistic_failure(pgdriver):
    pessimistic_failure(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pessimistic_failure():
    pessimistic_failure(util.MYSQL_POOL_URI)


def persistent_replaces_closed(uri):
    conn = connect_single(uri, persist=True, pessimistic=True)
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    cn2 = conn.get()
    assert cn2 is not cn1
    conn.put(cn2)
    assert conn.get() is cn2
    conn.put(cn2)
    conn.close()


@pytest.mark.postgres
def test_postgres_persistent_replaces_closed(pgdriver):
    persistent_replaces_closed(pgdriver.uri)


@pytest.mark.mysql
def test_mysql_persistent_replaces_closed():
    persistent_replaces_closed(util.MYSQL_URI)


def pool_replaces_closed(uri):
    conn = connect_pool(uri, size=1, overflow=0, pessimistic=True)
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    cn2 = conn.get()
    assert cn2 is not cn1
    conn.put(cn2)
    assert conn.checkedout == 0
    assert conn.get() is cn2
    conn.put(cn2)
    conn.close()


@pytest.mark.postgres
def test_postgres_pool_replaces_closed(pgdriver):
    pool_replaces_closed(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pool_replaces_closed():
    pool_replaces_closed(util.MYSQL_POOL_URI)


def finite_pool(uri):
    conn = connect(uri, size=1, overflow=4, timeout=0.05)
    conns = queue.Queue()
    exces = queue.Queue()

    def addconn(conns, conn):
        try:
            conns.put(conn.get())
        except exc.TimeoutError as e:
            assert str(e).startswith("QueuePool limit of size")
            exces.put(e)

    ts = []
    for _ in range(20):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        ts.append(t)
    for t in ts:
        t.join()

    # qsize returns the approximate size of the queue.
    # The result should be 15 but we can't be sure.
    assert exces.qsize() > 10

    while not conns.empty():
        c = conns.get()
        conn.put(c)
    conn.close()


@pytest.mark.postgres
def test_postgres_finite_pool(pgdriver):
    finite_pool(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_finite_pool():
    finite_pool(util.MYSQL_POOL_URI)


def infinite_pool(uri):
    conn = connect(uri, size=1, overflow=-1)
    conns = queue.Queue()

    def addconn(conns, conn):
        conns.put(conn.get())

    threads = []
    for _ in range(20):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    threads = []
    for _ in range(5):
        c = conns.get()
        conn.put(c)
    for _ in range(10):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    assert conns.qsize() == 25

    while not conns.empty():
        c = conns.get()
        conn.put(c)
    conn.close()


@pytest.mark.postgres
def test_postgres_infinite_pool(pgdriver):
    infinite_pool(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_infinite_pool():
    infinite_pool(util.MYSQL_POOL_URI)


def persistent_pool(uri, sqldirs):
    with pytest.raises(ValueError) as e:
        Database(uri, sqldirs, persist=True)
    assert str(e.value).startswith("Persistent connections")


@pytest.mark.postgres
def test_postgres_persistent_pool(pgdriver, pyformat_sqldirs):
    persistent_pool(pgdriver.pool_uri, pyformat_sqldirs)


@pytest.mark.mysql
def test_mysql_persistent_pool(pyformat_sqldirs):
    persistent_pool(util.MYSQL_POOL_URI, pyformat_sqldirs)


def failing_check(uri, error):
    conn = connect_single(uri, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(error)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)


@pytest.mark.postgres
def test_postgres_failing_check(pgdriver):
    failing_check(pgdriver.uri, pgdriver.dbapi.OperationalError)


@pytest.mark.mysql
def test_mysql_failing_check():
    import MySQLdb

    failing_check(util.MYSQL_URI, MySQLdb.OperationalError)


def test_sqlite_failing_connection():
    with pytest.raises(exc.ConnectionError):
        connect("sqlite:/// \n//\r /").get()


@pytest.mark.mysql
def test_mysql_failing_connection():
    with pytest.raises(exc.ConnectionError):
        connect("mysql://wrong_user_n4me:wrong_p4$$wrd@/wrng_db_n4me").get()


@pytest.mark.postgres
def test_postgresql_failing_connection(pgdriver):
    with pytest.raises(exc.ConnectionError):
        connect(
            pgdriver.name + "://wrong_user_n4me:wrong_p4$$wrd@/wrng_db_n4me"
        ).get()
