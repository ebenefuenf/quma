from psycopg2.extensions import connection
from psycopg2.pool import ThreadedConnectionPool
import pytest

from . import util
from .. import (
    Postgres,
    PostgresPool,
)


@pytest.mark.postgres
def test_postgres():
    conn = Postgres(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    cn = conn.get()
    assert conn.conn is None
    assert type(cn) is connection
    cn.close()


@pytest.mark.postgres
def test_postgres_conn():
    conn = Postgres(util.DB_NAME, user=util.DB_USER,
                    password=util.DB_PASS)
    cn = conn.get()
    assert conn.conn == cn
    assert type(cn) is connection
    conn.close()
    assert conn.conn is None


@pytest.mark.postgres
def test_postgres_pool():
    conn = PostgresPool(util.DB_NAME, user=util.DB_USER, password=util.DB_PASS)
    assert type(conn.conn) is ThreadedConnectionPool
    conn.close()
    assert conn.conn is None
