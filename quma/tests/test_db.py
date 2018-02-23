from quma import db


def test_init(conn, sqldirs):
    db.db.init(conn, sqldirs)
    assert 'addresses' in db.db.ns
    assert 'users' in db.db.ns
