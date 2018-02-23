import pathlib

import pytest

from quma import pool


@pytest.fixture(scope='module')
def conn():
    c = pool.Pool('quma_test_db',
                  user='quma_test_user',
                  password='quma_test_password')
    yield c
    c.disconnect()


@pytest.fixture(scope='module')
def sqldirs():
    return [
        pathlib.Path(__file__).parent / 'fixtures' / 'queries'
    ]
