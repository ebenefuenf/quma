import pytest

from . import util
from .. import (
    Postgres,
    PostgresPool,
)

try:
    from psycopg2.extensions import connection
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    pass


@pytest.mark.postgres
def test_postgres_non_persistent():
    conn = Postgres(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    assert conn.conn is None
    cn = conn.get()
    assert conn.conn is not None
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is None
    cn.close()


@pytest.mark.postgres
def test_postgres_persistent():
    conn = Postgres(util.DB_NAME, user=util.DB_USER,
                    password=util.DB_PASS, persist=True)
    cn = conn.get()
    assert conn.conn == cn
    assert type(cn) is connection
    conn.put(cn)
    assert conn.conn is not None


@pytest.mark.postgres
def test_postgres_pool():
    conn = PostgresPool(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    assert type(conn.conn) is ThreadedConnectionPool
    conn.close()
    assert conn.conn is None
    # TODO: getconn, putconn, multiple connections
