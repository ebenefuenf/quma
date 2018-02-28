import pathlib

import pytest

from . import pg
from .. import Database
from .. import conn as connection


@pytest.fixture(scope='module')
def conn():
    c = connection.PostgresPool(pg.DB_NAME,
                                user=pg.DB_USER,
                                password=pg.DB_PASS)
    yield c
    c.close()


@pytest.fixture(scope='module')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]


@pytest.fixture(scope='module')
def db(conn, sqldirs):
    db = Database(conn, sqldirs)
    return db
