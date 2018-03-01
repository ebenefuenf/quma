import pathlib

import pytest

from . import util
from .. import Database
from .. import conn as connection


@pytest.fixture(scope='module')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]


@pytest.fixture(scope='module')
def pgpoolconn():
    c = connection.PostgresPool(util.DB_NAME,
                                user=util.DB_USER,
                                password=util.DB_PASS)
    yield c
    c.close()


@pytest.fixture(scope='module')
def pgpooldb(pgpoolconn, sqldirs):
    db = Database(pgpoolconn, sqldirs)
    return db


@pytest.fixture(scope='module')
def pgconn():
    c = connection.PostgresPool(util.DB_NAME,
                                user=util.DB_USER,
                                password=util.DB_PASS)
    yield c
    c.close()


@pytest.fixture(scope='module')
def pgdb(pgconn, sqldirs):
    db = Database(pgconn, sqldirs)
    return db


@pytest.fixture(scope='module')
def slconn():
    c = connection.SQLite(':memory:')
    yield c
    c.close()


@pytest.fixture(scope='module')
def sldb(slconn, sqldirs):
    db = Database(slconn, sqldirs)
    return db
