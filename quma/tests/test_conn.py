import pytest

from . import util
from .. import connect
from .. import exc


@pytest.mark.postgres
def test_postgres_non_persistent():
    from psycopg2.extensions import connection

    conn = connect(util.PG_URI)
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

    conn = connect(util.PG_URI, persist=True)
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
def test_postgres_pool():
    from psycopg2.extensions import connection
    from psycopg2.pool import ThreadedConnectionPool, PoolError

    conn = connect(util.PG_POOL_URI)
    assert type(conn.conn) is ThreadedConnectionPool
    cn1 = conn.get()
    cn2 = conn.get()
    assert type(cn1) is connection
    assert type(cn2) is connection
    assert cn1 != cn2
    conn.put(cn1)
    conn.put(cn2)
    with pytest.raises(PoolError):
        conn.put(cn2)
    conn.close()
    assert conn.conn is None


@pytest.mark.mysql
def test_mysql_non_persistent():
    from MySQLdb.connections import Connection

    conn = connect(util.MYSQL_URI)
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
