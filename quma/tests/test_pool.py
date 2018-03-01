from psycopg2.extensions import connection
from psycopg2.pool import ThreadedConnectionPool

from . import util
from .. import (
    Postgres,
    PostgresPool,
)


def test_postgres():
    conn = Postgres(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    cn = conn.get()
    assert conn._conn is None
    assert type(cn) is connection
    cn.close()


def test_postgres_persist():
    conn = Postgres(util.DB_NAME, user=util.DB_USER,
                    password=util.DB_PASS, persist=True)
    cn = conn.get()
    assert conn._conn == cn
    assert type(cn) is connection
    conn.close()
    assert conn._conn is None


def test_postgres_pool():
    conn = PostgresPool(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    assert type(conn._conn) is ThreadedConnectionPool
    conn.close()
    assert conn._conn is None
