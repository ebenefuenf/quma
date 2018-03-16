import pathlib

import pytest

from . import util
from .. import Database


@pytest.fixture('session')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]


@pytest.fixture
def pgpooldb(sqldirs):
    db = Database(util.PG_POOL_URI, sqldirs)
    return db


@pytest.fixture
def pgdb(sqldirs):
    db = Database(util.PG_URI, sqldirs, changeling=True)
    return db


@pytest.fixture
def pgdb_persist(sqldirs):
    db = Database(util.PG_URI, sqldirs, persist=True)
    return db


@pytest.fixture
def mydb(sqldirs):
    db = Database(util.MYSQL_URI, sqldirs)
    return db


@pytest.fixture
def db(sqldirs):
    db = Database(util.SQLITE_URI, sqldirs, changeling=True)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db_no_changeling(sqldirs):
    db = Database(util.SQLITE_URI, sqldirs)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db
