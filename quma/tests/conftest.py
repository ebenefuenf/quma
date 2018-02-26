import pathlib

import pytest

from . import pg
from .. import pool


@pytest.fixture(scope='module')
def conn():
    c = pool.Pool(pg.DB_NAME, user=pg.DB_USER, password=pg.DB_PASS)
    yield c
    c.disconnect()


@pytest.fixture(scope='module')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]
