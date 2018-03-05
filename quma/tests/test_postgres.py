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
        pgdb.user.add_pg(cursor,
                         name='Anneliese Günthner',
                         email='anneliese.guenthner@example.com')
        cursor.commit()
        pgdb.user.remove_pg(cursor, name='Anneliese Günthner')
        cursor.commit()
    finally:
        cursor.close()


@pytest.mark.postgres
def test_commit(pgdb, pgpooldb):
    for db in (pgdb, pgpooldb):
        with pgdb.cursor as cursor:
            pgdb.user.add_pg(cursor,
                             name='hans',
                             email='hans@example.com')
        with pgdb.cursor as cursor:
            with pytest.raises(DoesNotExistError):
                pgdb.user.by_name_pg.get(cursor, name='hans')

        with pgdb.cursor as cursor:
            pgdb.user.add_pg(cursor,
                             name='hans',
                             email='hans@example.com')
            cursor.commit()

        cursor = pgdb.cursor()
        pgdb.user.by_name_pg.get(cursor, name='hans')
        pgdb.user.remove_pg(cursor, name='hans')
        cursor.commit()
        with pytest.raises(DoesNotExistError):
            pgdb.user.by_name_pg.get(cursor, name='hans')
        cursor.close()


@pytest.mark.postgres
def test_rollback(pgdb):
    cursor = pgdb.cursor()
    pgdb.user.add_pg(cursor,
                     name='hans',
                     email='hans@example.com')
    pgdb.user.by_name_pg.get(cursor, name='hans')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        u = pgdb.user.by_name_pg.get(cursor, name='hans')
    cursor.close()


@pytest.mark.postgres
def test_changeling_cursor(pgdb):
    with pgdb.cursor as cursor:
        hans = pgdb.user.by_name_pg.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        assert hans.email == 'franz.goertler@example.com'
        assert 'email' in hans.keys()
