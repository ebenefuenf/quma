import pytest

from . import util
from .. import connect

try:
    from psycopg2.extensions import connection
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    pass


@pytest.mark.postgres
def test_postgres_non_persistent():
    conn = connect(util.PG_URI)
    assert conn.conn is None
    cn = conn.get()
    assert conn.conn is not None
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is None
    cn.close()


@pytest.mark.postgres
def test_postgres_persistent():
    conn = connect(util.PG_URI_PERSIST)
    cn = conn.get()
    assert conn.conn == cn
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is not None


@pytest.mark.postgres
def test_postgres_pool():
    conn = connect(util.PG_POOL_URI)
    assert type(conn.conn) is ThreadedConnectionPool
    conn.close()
    assert conn.conn is None
    # TODO: getconn, putconn, multiple connections
