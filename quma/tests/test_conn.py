import queue
import sqlite3
import threading
from unittest.mock import Mock

import pytest

from . import util
from .. import (
    Database,
    conn,
    connect,
    exc,
)


def get_cursor_mock(exception):
    def cursor():
        m = Mock()
        m.execute = Mock()
        m.execute.side_effect = exception
        return m
    return cursor


def test_base_connection(dburl):
    cn = conn.Connection(dburl, persist=True)
    assert cn.database == util.DB_NAME
    assert cn.username == util.DB_USER
    assert cn.password == util.DB_PASS
    assert cn.url == dburl
    c = Mock()
    cn.conn = c
    with pytest.raises(NotImplementedError):
        cn.check()
    cn.close()
    cn.close(c)
    assert c.close.call_count == 2


def test_failing_check():
    conn = connect(util.SQLITE_MEMORY, persist=True, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(sqlite3.ProgrammingError)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)
    connmock.cursor = get_cursor_mock(sqlite3.OperationalError)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)


def test_persistent_pessimistic(dbpess):
    with dbpess.cursor as cursor:
        cn = cursor.raw_conn
    with dbpess.cursor as cursor:
        assert cn is cursor.raw_conn
    dbpess.conn._check = Mock()
    dbpess.conn._check.side_effect = exc.OperationalError
    with dbpess.cursor as cursor:
        assert cn is not cursor.raw_conn


def pool_overflow_counting(uri):
    conn = connect(uri, size=1, overflow=4)
    cn1 = conn.get()
    cn2 = conn.get()
    conn.get()
    assert conn.overflow == 2
    conn.put(cn1)
    # Queue not full yet, overflow does not decrease
    assert conn.overflow == 2
    conn.put(cn2)
    # Queue is full now, overflow must be lower
    assert conn.overflow == 1
    conn.get()
    conn.get()
    assert conn.overflow == 2
    conn._conn.get = Mock()
    conn._conn.get.side_effect = ValueError
    with pytest.raises(ValueError):
        conn.get()
    assert conn.overflow == 2
    conn.close()


@pytest.mark.postgres
def test_postgres_pool_overflow_counting():
    pool_overflow_counting(util.PGSQL_POOL_URI)


@pytest.mark.mysql
def test_mysql_pool_overflow_counting():
    pool_overflow_counting(util.MYSQL_POOL_URI)


def non_persistent(uri, connection, pessimistic):
    conn = connect(uri, pessimistic=pessimistic)
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
    with pytest.raises(exc.APIError):
        conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_postgres_non_persistent(pessimistic):
    from psycopg2.extensions import connection
    non_persistent(util.PGSQL_URI, connection, pessimistic)


@pytest.mark.mysql
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_mysql_non_persistent(pessimistic):
    from MySQLdb.connections import Connection
    non_persistent(util.MYSQL_URI, Connection, pessimistic)


def persistent(uri, connection):
    conn = connect(uri, persist=True)
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


@pytest.mark.postgres
def test_postgres_persistent():
    from psycopg2.extensions import connection
    persistent(util.PGSQL_URI, connection)


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
    assert conn.status().startswith('Pool size: 5 Connections')
    assert conn.checkedin == 2
    cn3 = conn.get()
    assert conn.checkedin == 1
    assert cn3 == cn1
    conn.close()
    assert conn.checkedin == 0


@pytest.mark.postgres
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_postgres_pool(pessimistic):
    from psycopg2.extensions import connection
    pool(util.PGSQL_POOL_URI, pessimistic, connection)


@pytest.mark.mysql
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_mysql_pool(pessimistic):
    from MySQLdb.connections import Connection
    pool(util.MYSQL_POOL_URI, pessimistic, Connection)


def pessimistic_failure(uri):
    conn = connect(uri, size=1, overflow=-1, pessimistic=True)
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 == c2
    conn._conn.check = Mock()
    conn._conn.check.side_effect = exc.OperationalError
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 != c2


@pytest.mark.postgres
def test_postgres_pessimistic_failure():
    pessimistic_failure(util.PGSQL_POOL_URI)


@pytest.mark.mysql
def test_mysql_pessimistic_failure():
    pessimistic_failure(util.MYSQL_POOL_URI)


def finite_pool(uri):
    conn = connect(uri, size=1, overflow=4, timeout=0.05)
    conns = queue.Queue()
    exces = queue.Queue()

    def addconn(conns, conn):
        try:
            conns.put(conn.get())
        except exc.TimeoutError as e:
            assert str(e).startswith('QueuePool limit of size')
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
def test_postgres_finite_pool():
    finite_pool(util.PGSQL_POOL_URI)


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
def test_postgres_infinite_pool():
    infinite_pool(util.PGSQL_POOL_URI)


@pytest.mark.mysql
def test_mysql_infinite_pool():
    infinite_pool(util.MYSQL_POOL_URI)


def persistent_pool(uri, sqldirs):
    with pytest.raises(ValueError) as e:
        Database(uri, sqldirs, persist=True)
    assert str(e.value).startswith('Persistent connections')


@pytest.mark.postgres
def test_postgres_persistent_pool(pyformat_sqldirs):
    persistent_pool(util.PGSQL_POOL_URI, pyformat_sqldirs)


@pytest.mark.mysql
def test_mysql_persistent_pool(pyformat_sqldirs):
    persistent_pool(util.MYSQL_POOL_URI, pyformat_sqldirs)


def failing_check(uri, error):
    conn = connect(uri, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(error)
    with pytest.raises(exc.OperationalError):
        conn._check(connmock)


@pytest.mark.postgres
def test_postgres_failing_check():
    import psycopg2
    failing_check(util.PGSQL_URI, psycopg2.OperationalError)


@pytest.mark.mysql
def test_mysql_failing_check():
    import MySQLdb
    failing_check(util.MYSQL_URI, MySQLdb.OperationalError)
