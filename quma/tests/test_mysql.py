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
                      email='anneliese.guenthner@example.com',
                      city='city')
        cursor.commit()
        mydb.user.remove(cursor, name='Anneliese Günthner')
        cursor.commit()
    finally:
        cursor.close()


@pytest.mark.mysql
def test_commit(mydb):
    with mydb.cursor as cursor:
        mydb.user.add(cursor,
                      name='Test User',
                      email='test.user@example.com',
                      city='Test City')
    with mydb.cursor as cursor:
        with pytest.raises(DoesNotExistError):
            mydb.user.by_name.get(cursor, name='Test User')

    with mydb.cursor as cursor:
        mydb.user.add(cursor,
                      name='Test User',
                      email='test.user@example.com',
                      city='Test City')
        cursor.commit()

    cursor = mydb.cursor()
    mydb.user.by_name.get(cursor, name='Test User')
    mydb.user.remove(cursor, name='Test User')
    cursor.commit()
    with pytest.raises(DoesNotExistError):
        mydb.user.by_name.get(cursor, name='Test User')
    cursor.close()


@pytest.mark.mysql
def test_rollback(mydb):
    cursor = mydb.cursor()
    mydb.user.add(cursor,
                  name='Test User',
                  email='test.user@example.com',
                  city='Test City')
    mydb.user.by_name.get(cursor, name='Test User')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        mydb.user.by_name.get(cursor, name='Test User')
    cursor.close()


@pytest.mark.mysql
def test_tuple_cursor(mydb_persist):
    # pgdb_persist does not use the changeling factory
    with mydb_persist.cursor as cursor:
        user = mydb_persist.user.by_name.get(cursor, name='User 4')
        assert user[0] == 'user.4@example.com'
        with pytest.raises(TypeError):
            user['email']
        cursor.rollback()


@pytest.mark.mysql
def test_dict_cursor(mydb):
    # pgdb_persist does not use the changeling factory
    with mydb.cursor as cursor:
        user = mydb.user.by_name.get(cursor, name='User 3')
        assert user['email'] == 'user.3@example.com'
        with pytest.raises(KeyError):
            user[0]
        cursor.rollback()