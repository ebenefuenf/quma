import pathlib

import pytest

from . import pg
from .. import Database
from .. import conn as connection


@pytest.fixture(scope='module')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]


@pytest.fixture(scope='module')
def pgpoolconn():
    c = connection.PostgresPool(pg.DB_NAME,
                                user=pg.DB_USER,
                                password=pg.DB_PASS)
    yield c
    c.close()


@pytest.fixture(scope='module')
def pgpooldb(pgpoolconn, sqldirs):
    db = Database(pgpoolconn, sqldirs)
    return db


@pytest.fixture(scope='module')
def pgconn():
    c = connection.PostgresPool(pg.DB_NAME,
                                user=pg.DB_USER,
                                password=pg.DB_PASS)
    yield c
    c.close()


@pytest.fixture(scope='module')
def pgdb(pgconn, sqldirs):
    db = Database(pgconn, sqldirs)
    return db
