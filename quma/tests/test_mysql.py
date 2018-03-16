import pytest

from . import util
from ..exc import DoesNotExistError
from ..mapper import Cursor


def setup_function(function):
    util.setup_mysql_db()


@pytest.mark.mysql
def test_cursor(mydb):
    with mydb().cursor as cursor:
        assert type(cursor) is Cursor
        assert len(mydb.users.all(cursor)) == 4


@pytest.mark.mysql
def test_cursor_call(mydb):
    cursor = mydb.cursor()
    try:
        mydb.user.add(cursor,
                      name='Anneliese Günthner',
                      email='anneliese.guenthner@example.com')
        cursor.commit()
        mydb.user.remove(cursor, name='Anneliese Günthner')
        cursor.commit()
    finally:
        cursor.close()


@pytest.mark.mysql
def test_commit(mydb):
    with mydb.cursor as cursor:
        mydb.user.add(cursor,
                      name='hans',
                      email='hans@example.com')
    with mydb.cursor as cursor:
        with pytest.raises(DoesNotExistError):
            mydb.user.by_name.get(cursor, name='hans')

    with mydb.cursor as cursor:
        mydb.user.add(cursor,
                      name='hans',
                      email='hans@example.com')
        cursor.commit()

    cursor = mydb.cursor()
    mydb.user.by_name.get(cursor, name='hans')
    mydb.user.remove(cursor, name='hans')
    cursor.commit()
    with pytest.raises(DoesNotExistError):
        mydb.user.by_name.get(cursor, name='hans')
    cursor.close()


@pytest.mark.mysql
def test_rollback(mydb):
    cursor = mydb.cursor()
    mydb.user.add(cursor,
                  name='hans',
                  email='hans@example.com')
    mydb.user.by_name.get(cursor, name='hans')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        mydb.user.by_name.get(cursor, name='hans')
    cursor.close()


@pytest.mark.mysql
def test_no_changeling_cursor(mydb_persist):
    # pgdb_persist does not use the changeling factory
    with mydb_persist.cursor as cursor:
        hans = mydb_persist.user.by_name.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        with pytest.raises(AttributeError):
            hans.email
        cursor.rollback()
