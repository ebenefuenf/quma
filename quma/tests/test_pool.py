from psycopg2.pool import ThreadedConnectionPool

from . import pg
from .. import PostgresPool


def test_connection():
    conn = PostgresPool(pg.DB_NAME, user=pg.DB_USER, password=pg.DB_PASS)
    assert type(conn._pool) is ThreadedConnectionPool
    conn.disconnect()
    assert conn._pool is None
