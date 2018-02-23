from quma.db import db, Namespace


def test_init(conn, sqldirs):
    db.init(conn, sqldirs)
    assert 'addresses' in db.ns
    assert 'users' in db.ns


def test_namespace(conn, sqldirs):
    db.init(conn, sqldirs)
    assert type(db.addresses) is Namespace
    assert type(db.users) is Namespace
    assert db.users.all.startswith('SELECT * FROM users')
