from psycopg2.pool import ThreadedConnectionPool

from quma import pool


def test_connection():
    conn = pool.Pool('quma_test_db',
                     user='quma_test_user',
                     password='quma_test_password')
    assert type(conn._pool) is ThreadedConnectionPool
    conn.disconnect()
    assert conn._pool is None
