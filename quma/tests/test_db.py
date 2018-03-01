import pytest

from . import util
from .. import (
    Database,
    Namespace,
)
from ..exc import DoesNotExistError
from ..mapper import (
    Cursor,
    Query,
)


def setup_function(function):
    util.setup_pg_db()


def test_init(pgdb):
    assert 'addresses' in pgdb.namespaces
    assert 'users' in pgdb.namespaces


def test_failing_init(pgdb):
    with pytest.raises(ValueError) as e:
        Database(1, 2, 3)
    assert 'Max number' in str(e)


def test_namespace(pgpooldb):
    assert type(pgpooldb.addresses) is Namespace
    assert isinstance(pgpooldb.users, Namespace)


def test_query(pgdb):
    assert str(pgdb.users.all).startswith('SELECT * FROM users')


def test_cursor(pgdb):
    with pgdb().cursor as cursor:
        assert type(cursor) is Cursor
        assert len(pgdb.users.all(cursor)) == 4


def test_custom_namespace(pgdb):
    with pgdb.cursor as cursor:
        assert type(pgdb.users).__module__ == 'quma.mapping.users'
        assert type(pgdb.users).__name__ == 'Users'
        assert pgdb.users.get_hans(cursor) == 'Hans'
        # Test the namespace alias
        assert pgdb.user.get_hans(cursor) == 'Hans'


def test_cursor_call(pgdb):
    cursor = pgdb.cursor()
    try:
        pgdb.user.add(cursor,
                      name='Anneliese Günthner',
                      email='anneliese.guenthner@example.com')
        cursor.commit()
        pgdb.user.remove(cursor, name='Anneliese Günthner')
        cursor.commit()
    finally:
        cursor.close()


def test_commit(pgdb):
    with pgdb.cursor as cursor:
        pgdb.user.add(cursor,
                      name='hans',
                      email='hans@example.com')
    with pgdb.cursor as cursor:
        with pytest.raises(DoesNotExistError):
            pgdb.user.by_name.get(cursor, name='hans')

    with pgdb.cursor as cursor:
        pgdb.user.add(cursor,
                      name='hans',
                      email='hans@example.com')
        cursor.commit()

    cursor = pgdb.cursor()
    pgdb.user.by_name.get(cursor, name='hans')
    pgdb.user.remove(cursor, name='hans')
    cursor.commit()
    with pytest.raises(DoesNotExistError):
        pgdb.user.by_name.get(cursor, name='hans')
    cursor.close()


def test_rollback(pgdb):
    cursor = pgdb.cursor()
    pgdb.user.add(cursor,
                  name='hans',
                  email='hans@example.com')
    pgdb.user.by_name.get(cursor, name='hans')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        pgdb.user.by_name.get(cursor, name='hans')
    cursor.close()


def test_overwrite_query_class(pgpoolconn, sqldirs):
    class MyQuery(Query):
        def the_test(self):
            return 'Hans Karl'
    pgdb = Database(pgpoolconn, sqldirs, query_factory=MyQuery)
    assert pgdb.user.all.the_test() == 'Hans Karl'


def test_changeling_cursor(pgdb):
    with pgdb.cursor as cursor:
        hans = pgdb.user.by_name.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        assert hans.email == 'franz.goertler@example.com'
        assert 'email' in hans.keys()
