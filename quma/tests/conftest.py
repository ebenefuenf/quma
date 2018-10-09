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
    p = pathlib.Path(__file__).parent / 'fixtures' / 'scripts' / 'pyformat'
    return str(p)


@pytest.fixture('session')
def qmark_sqldirs():
    return pathlib.Path(__file__).parent / 'fixtures' / 'scripts' / 'qmark'


@pytest.fixture('session')
def qmark_shadow_sqldirs():
    parent = pathlib.Path(__file__).parent
    return [
        parent / 'fixtures' / 'scripts' / 'qmark',
        str(parent / 'fixtures' / 'scripts' / 'qmark_shadow'),
    ]


@pytest.fixture
def db(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  persist=True,
                  sqldirs=qmark_sqldirs,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbpess(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  persist=True,
                  pessimistic=True,
                  sqldirs=qmark_sqldirs,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbshow(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  qmark_sqldirs,
                  persist=True,
                  changeling=True, show=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbcache(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  qmark_sqldirs,
                  persist=True,
                  changeling=True,
                  cache=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbshadow(qmark_shadow_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  qmark_shadow_sqldirs,
                  persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbfile(qmark_sqldirs):
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI,
                  qmark_sqldirs,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbcommit(qmark_sqldirs):
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI,
                  qmark_sqldirs,
                  contextcommit=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db_no_changeling(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY,
                  qmark_sqldirs,
                  persist=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbdictcb(qmark_sqldirs):
    def dict_callback(carrier, params):
        params['name'] = carrier.name
        return params

    db = Database(util.SQLITE_MEMORY,
                  qmark_sqldirs,
                  prepare_params=dict_callback,
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

    db = Database(util.SQLITE_MEMORY,
                  qmark_sqldirs,
                  prepare_params=sequence_callback,
                  persist=True,
                  changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def pgpooldb(pyformat_sqldirs):
    db = Database(util.PGSQL_POOL_URI,
                  pyformat_sqldirs,
                  changeling=True)
    return db


@pytest.fixture
def pgdb(pyformat_sqldirs):
    db = Database(util.PGSQL_URI,
                  pyformat_sqldirs,
                  changeling=True)
    return db


@pytest.fixture
def pgdb_persist(pyformat_sqldirs):
    db = Database(util.PGSQL_URI,
                  pyformat_sqldirs,
                  persist=True)
    return db


@pytest.fixture
def mydb(pyformat_sqldirs):
    db = Database(util.MYSQL_URI,
                  pyformat_sqldirs,
                  dict_cursor=True)
    return db


@pytest.fixture
def mypooldb(pyformat_sqldirs):
    db = Database(util.MYSQL_POOL_URI, pyformat_sqldirs)
    return db


@pytest.fixture
def mypooldbdict(pyformat_sqldirs):
    db = Database(util.MYSQL_POOL_URI,
                  pyformat_sqldirs,
                  dict_cursor=True)
    return db


@pytest.fixture
def mydbpersist(pyformat_sqldirs):
    db = Database(util.MYSQL_URI,
                  pyformat_sqldirs,
                  persist=True)
    return db


@pytest.fixture
def carrier():
    return SimpleNamespace(name='User 1',
                           email='user.1@example.com')
