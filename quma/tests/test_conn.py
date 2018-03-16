import pytest

from . import util
from .. import connect


@pytest.mark.postgres
def test_postgres_non_persistent():
    from psycopg2.extensions import connection

    conn = connect(util.PG_URI)
    assert conn.conn is None
    cn = conn.get()
    assert conn.conn is not None
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is None


@pytest.mark.postgres
def test_postgres_persistent():
    from psycopg2.extensions import connection

    conn = connect(util.PG_URI, persist=True)
    cn = conn.get()
    assert conn.conn == cn
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is not None


@pytest.mark.postgres
def test_postgres_pool():
    from psycopg2.pool import ThreadedConnectionPool

    conn = connect(util.PG_POOL_URI)
    assert type(conn.conn) is ThreadedConnectionPool
    conn.close()
    assert conn.conn is None
    # TODO: getconn, putconn, multiple connections


@pytest.mark.mysql
def test_mysql_non_persistent():
    from MySQLdb.connections import Connection

    conn = connect(util.MYSQL_URI)
    assert conn.conn is None
    cn = conn.get()
    assert conn.conn is not None
    assert type(cn) is Connection
    conn.put(cn)
    assert conn.conn is None
