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
    db = Database(util.PG_URI, sqldirs)
    return db


@pytest.fixture
def db(sqldirs):
    db = Database('sqlite:////tmp/quma.sqlite', sqldirs)
    db.execute(util.DROP_USERS)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db
