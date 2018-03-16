import pathlib

import pytest

from . import util
from .. import Database


@pytest.fixture('session')
def pyformat_sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries' / 'pyformat'
    ]


@pytest.fixture('session')
def qmark_sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries' / 'qmark'
    ]


@pytest.fixture
def pgpooldb(pyformat_sqldirs):
    db = Database(util.PG_POOL_URI, pyformat_sqldirs)
    return db


@pytest.fixture
def pgdb(pyformat_sqldirs):
    db = Database(util.PG_URI, pyformat_sqldirs, changeling=True)
    return db


@pytest.fixture
def pgdb_persist(pyformat_sqldirs):
    db = Database(util.PG_URI, pyformat_sqldirs, persist=True)
    return db


@pytest.fixture
def mydb(pyformat_sqldirs):
    db = Database(util.MYSQL_URI, pyformat_sqldirs, dict_cursor=True)
    return db


@pytest.fixture
def mydb_persist(pyformat_sqldirs):
    db = Database(util.MYSQL_URI, pyformat_sqldirs, persist=True)
    return db


@pytest.fixture
def db(qmark_sqldirs):
    db = Database(util.SQLITE_URI, qmark_sqldirs, changeling=True)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db_no_changeling(qmark_sqldirs):
    db = Database(util.SQLITE_URI, qmark_sqldirs)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db
