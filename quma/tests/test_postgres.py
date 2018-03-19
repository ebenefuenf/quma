import pytest

from . import util
from ..exc import DoesNotExistError
from ..mapper import Cursor


def setup_function(function):
    util.setup_pg_db()


@pytest.mark.postgres
def test_cursor(pgdb):
    with pgdb().cursor as cursor:
        assert type(cursor) is Cursor
        assert len(pgdb.users.all(cursor)) == 4


@pytest.mark.postgres
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


@pytest.mark.postgres
def test_commit(pgdb, pgpooldb):
    for db in (pgdb, pgpooldb):
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


@pytest.mark.postgres
def test_conn_attr(pgdb):
    with pgdb.cursor as c:
        assert c.raw_conn.autocommit is False
        assert c.get_conn_attr('autocommit') is c.raw_conn.autocommit
        c.set_conn_attr('autocommit', True)
        assert c.raw_conn.autocommit is True
        assert c.get_conn_attr('autocommit') is c.raw_conn.autocommit
        pgdb.user.add(c,
                      name='hans',
                      email='hans@example.com')
        # no explicit commit
    with pgdb.cursor as cursor:
        assert cursor.get_conn_attr('autocommit') is False
        user = pgdb.user.by_name.get(cursor, name='hans')
    assert user.email == 'hans@example.com'


@pytest.mark.postgres
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


@pytest.mark.postgres
def test_changeling_cursor(pgdb):
    with pgdb.cursor as cursor:
        hans = pgdb.user.by_name.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        assert hans.email == 'franz.goertler@example.com'
        with pytest.raises(AttributeError):
            hans.wrong_attr
        assert 'email' in hans.keys()


@pytest.mark.postgres
def test_no_changeling_cursor(pgdb_persist):
    # pgdb_persist does not use the changeling factory
    with pgdb_persist.cursor as cursor:
        hans = pgdb_persist.user.by_name.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        with pytest.raises(AttributeError):
            hans.email
        cursor.rollback()
