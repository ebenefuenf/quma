from unittest.mock import Mock
import pytest
import queue
import threading
import time

from . import util
from .. import conn
from .. import (
    connect,
    Database,
)
from .. import exc


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


@pytest.mark.postgres
def test_postgres_non_persistent():
    from psycopg2.extensions import connection

    conn = connect(util.PGSQL_URI)
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
def test_postgres_persistent():
    from psycopg2.extensions import connection

    conn = connect(util.PGSQL_URI, persist=True)
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
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_postgres_pool(pessimistic):
    from psycopg2.extensions import connection
    from .. import pool

    conn = connect(util.PGSQL_POOL_URI, pessimistic=pessimistic)
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
    assert conn.checkedin == 2
    cn3 = conn.get()
    assert conn.checkedin == 1
    assert cn3 == cn1
    conn.close()
    assert conn.checkedin == 0


@pytest.mark.postgres
def test_postgres_finit_pool():
    conn = connect(util.PGSQL_POOL_URI, size=1, overflow=4, timeout=0.05)
    conns = queue.Queue()
    exces = queue.Queue()

    def addconn(conns, conn):
        try:
            conns.put(conn.get())
        except exc.TimeoutError as e:
            assert str(e).startswith('QueuePool limit of size')
            exces.put(e)

    for _ in range(20):
        threading.Thread(target=addconn, args=(conns, conn)).start()
    time.sleep(0.1)

    assert exces.qsize() == 15

    while not conns.empty():
        c = conns.get()
        conn.put(c)
    conn.close()


@pytest.mark.postgres
def test_postgres_infinit_pool():
    conn = connect(util.PGSQL_POOL_URI, size=1, overflow=-1)
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
def test_postgres_persistent_pool(pyformat_sqldirs):
    from . import util
    with pytest.raises(ValueError) as e:
        Database(util.PGSQL_POOL_URI, pyformat_sqldirs, persist=True)
    assert str(e.value).startswith('Persistent connections')


@pytest.mark.mysql
@pytest.mark.parametrize('pessimistic', [
    False,
    True,
])
def test_mysql_non_persistent(pessimistic):
    from MySQLdb.connections import Connection

    conn = connect(util.MYSQL_URI, pessimistic=pessimistic)
    cn1 = conn.get()
    assert cn1.open == 1
    with pytest.raises(AttributeError):
        conn.conn
    assert type(cn1) is Connection
    cn2 = conn.get()
    assert cn1 != cn2
    conn.put(cn1)
    assert cn1.open == 0
    assert cn2.open == 1
    conn.put(cn2)
    assert cn2.open == 0
    with pytest.raises(exc.APIError):
        conn.close()


@pytest.mark.mysql
def test_mysql_persistent():
    from MySQLdb.connections import Connection

    conn = connect(util.MYSQL_URI, persist=True)
    cn1 = conn.get()
    assert cn1.closed == 0
    assert conn.conn == cn1
    assert type(cn1) is Connection
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


@pytest.mark.mysql
def test_mysql_pool():
    from MySQLdb.connections import Connection
    from .. import pool

    conn = connect(util.MYSQL_POOL_URI)
    assert type(conn) is pool.Pool
    assert conn.size == 5
    cn1 = conn.get()
    assert conn.overflow == -4
    cn2 = conn.get()
    assert conn.overflow == -3
    assert type(cn1) is Connection
    assert type(cn2) is Connection
    assert cn1 != cn2
    conn.put(cn1)
    conn.put(cn2)
    assert conn.checkedin == 2
    cn3 = conn.get()
    assert conn.checkedin == 1
    assert cn3 == cn1
    conn.close()
    assert conn.checkedin == 0


@pytest.mark.mysql
def test_mysql_persistent_pool(pyformat_sqldirs):
    from . import util
    with pytest.raises(ValueError) as e:
        Database(util.MYSQL_POOL_URI, pyformat_sqldirs, persist=True)
    assert str(e.value).startswith('Persistent connections')


@pytest.mark.mysql
def test_mysql_finit_pool():
    conn = connect(util.MYSQL_POOL_URI, size=1, overflow=4, timeout=0.1)
    conns = []
    with pytest.raises(exc.TimeoutError) as e:
        for _ in range(20):
            conns.append(conn.get())
    assert str(e.value).startswith('QueuePool limit of size')
    while conns:
        c = conns.pop()
        conn.put(c)
    conn.close()


@pytest.mark.mysql
def test_mysql_infinit_pool():
    conn = connect(util.MYSQL_POOL_URI, size=1, overflow=-1, pessimistic=True)
    conns = []
    for _ in range(20):
        conns.append(conn.get())
    for _ in range(5):
        c = conns.pop()
        conn.put(c)
    for _ in range(10):
        conns.append(conn.get())
    assert len(conns) == 25
    while conns:
        c = conns.pop()
        conn.put(c)
    conn.close()
