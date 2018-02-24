from psycopg2.pool import ThreadedConnectionPool

from .. import Pool
from . import pg


def test_connection():
    conn = Pool(pg.DB_NAME, user=pg.DB_USER, password=pg.DB_PASS)
    assert type(conn._pool) is ThreadedConnectionPool
    conn.disconnect()
    assert conn._pool is None
