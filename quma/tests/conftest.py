import pathlib

import pytest

from . import util
from .. import Database
from .. import conn as connection


@pytest.fixture('session')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]


@pytest.fixture
def pgpoolconn():
    c = connection.PostgresPool(util.DB_NAME,
                                user=util.DB_USER,
                                password=util.DB_PASS)
    yield c
    c.close()


@pytest.fixture
def pgpooldb(pgpoolconn, sqldirs):
    db = Database(pgpoolconn, sqldirs)
    return db


@pytest.fixture
def pgconn():
    c = connection.PostgresPool(util.DB_NAME,
                                user=util.DB_USER,
                                password=util.DB_PASS)
    yield c
    c.close()


@pytest.fixture
def pgdb(pgconn, sqldirs):
    db = Database(pgconn, sqldirs)
    return db


@pytest.fixture
def conn():
    c = connection.SQLite('/tmp/quma.sqlite3')
    yield c
    c.close()


@pytest.fixture
def db(conn, sqldirs):
    cursor = conn.cursor()
    cursor.execute(util.DROP_USERS)
    cursor.execute(util.CREATE_USERS)
    cursor.execute(util.INSERT_USERS)
    conn.conn.commit()
    db = Database(conn, sqldirs)
    return db
