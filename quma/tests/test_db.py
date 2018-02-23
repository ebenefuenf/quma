from pathlib import Path

from quma import (
    db,
    pool,
)


def test_init():
    conn = pool.Pool('quma_test_db',
                     user='quma_test_user',
                     password='quma_test_password')

    script_dirs = [Path(__file__).parent / 'fixtures' / 'queries']
    db.db.init(conn, script_dirs)
    assert 'addresses' in db.db.ns
    assert 'users' in db.db.ns
