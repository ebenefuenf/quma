import pathlib
from types import SimpleNamespace

import pytest

from . import util
from .. import Database


@pytest.fixture
def dburl():
    from urllib.parse import urlparse
    return urlparse(util.PGSQL_URI)


@pytest.fixture('session')
def pyformat_sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries' / 'pyformat'
    ]


@pytest.fixture('session')
def qmark_sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries' / 'qmark',
    ]


@pytest.fixture('session')
def qmark_shadow_sqldirs():
    parent = pathlib.Path(__file__).parent
    return [
        parent / 'fixtures' / 'queries' / 'qmark',
        parent / 'fixtures' / 'queries' / 'qmark_shadow',
    ]


@pytest.fixture
def pgpooldb(pyformat_sqldirs):
    db = Database(util.PGSQL_POOL_URI, pyformat_sqldirs)
    return db


@pytest.fixture
def pgdb(pyformat_sqldirs):
    db = Database(util.PGSQL_URI, pyformat_sqldirs, changeling=True)
    return db


@pytest.fixture
def pgdb_persist(pyformat_sqldirs):
    db = Database(util.PGSQL_URI, pyformat_sqldirs, persist=True)
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
def dbshow(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY, qmark_sqldirs, persist=True,
                  changeling=True, show=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY, qmark_sqldirs, persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbshadow(qmark_shadow_sqldirs):
    db = Database(util.SQLITE_MEMORY, qmark_shadow_sqldirs, persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbfile(qmark_sqldirs):
    db = Database(util.SQLITE_URI, qmark_sqldirs, changeling=True)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db_no_changeling(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY, qmark_sqldirs, persist=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbdictcb(qmark_sqldirs):
    def dict_callback(carrier, params):
        params['name'] = carrier.name
        return params

    db = Database(util.SQLITE_MEMORY, qmark_sqldirs,
                  init_params=dict_callback,
                  persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbseqcb(qmark_sqldirs):
    def sequence_callback(carrier, params):
        params.append(carrier.email)
        return params

    db = Database(util.SQLITE_MEMORY, qmark_sqldirs,
                  init_params=sequence_callback,
                  persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def carrier():
    return SimpleNamespace(name='User 1',
                           email='user.1@example.com')
