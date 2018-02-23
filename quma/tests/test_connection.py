from psycopg2.pool import ThreadedConnectionPool

from quma import connection


def test_connection():
    conn = connection.Connection('quma_test_db',
                                 user='quma_test_user',
                                 password='quma_test_password')
    conn.connect()
    assert type(conn._pool) is ThreadedConnectionPool
    conn.disconnect()
    assert conn._pool is None
