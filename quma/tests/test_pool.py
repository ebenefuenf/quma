from psycopg2.extensions import connection
from psycopg2.pool import ThreadedConnectionPool

from . import pg
from .. import (
    Postgres,
    PostgresPool,
)


def test_postgres():
    conn = Postgres(pg.DB_NAME, user=pg.DB_USER, password=pg.DB_PASS)
    cn = conn.get()
    assert conn._conn is None
    assert type(cn) is connection
    cn.close()


def test_postgres_persist():
    conn = Postgres(pg.DB_NAME, user=pg.DB_USER,
                    password=pg.DB_PASS, persist=True)
    cn = conn.get()
    assert conn._conn == cn
    assert type(cn) is connection
    conn.close()
    assert conn._conn is None


def test_postgres_pool():
    conn = PostgresPool(pg.DB_NAME, user=pg.DB_USER, password=pg.DB_PASS)
    assert type(conn._conn) is ThreadedConnectionPool
    conn.close()
    assert conn._conn is None
