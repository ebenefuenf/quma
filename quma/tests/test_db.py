from .. import db, Namespace
from ..mapper import Cursor
from . import pg


def setup_function(function):
    pg.setup_db()


def test_init(conn, sqldirs):
    db.init(conn, sqldirs)
    assert 'addresses' in db.ns
    assert 'users' in db.ns


def test_namespace(conn, sqldirs):
    db.init(conn, sqldirs)
    assert type(db.addresses) is Namespace
    assert type(db.users) is Namespace


def test_query(conn, sqldirs):
    db.init(conn, sqldirs)
    assert str(db.users.all).startswith('SELECT * FROM users')


def test_cursor(conn, sqldirs):
    db.init(conn, sqldirs)
    with db().cursor as cursor:
        assert type(cursor) is Cursor
        assert len(db.users.all.all(cursor)) == 4
