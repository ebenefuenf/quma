import pytest

from . import util
from ..exc import DoesNotExistError
from ..mapper import Cursor


def setup_function(function):
    util.setup_mysql_db()


@pytest.mark.mysql
def test_mysql_conn_attr(mydb, mypooldb):
    from .test_db import conn_attr
    for db in (mydb, mypooldb):
        conn_attr(db, 'encoding', 'latin1', 'utf-8')


@pytest.mark.mysql
def test_mysql_cursor(mydb, mypooldb):
    from .test_db import cursor
    for db in (mydb, mypooldb):
        cursor(db)


@pytest.mark.mysql
def test_mysql_cursor_call(mydb, mypooldb):
    from .test_db import cursor_call
    for db in (mydb, mypooldb):
        cursor_call(db)


@pytest.mark.mysql
def test_mysql_commit(mydb, mypooldb):
    from .test_db import commit
    for db in (mydb, mypooldb):
        commit(db)


@pytest.mark.mysql
def test_mysql_rollback(mydb, mypooldb):
    from .test_db import rollback
    for db in (mydb, mypooldb):
        rollback(db)


@pytest.mark.mysql
def test_mysql_multiple_records(mydb, mypooldb):
    from .test_db import multiple_records
    multiple_records(mydb, lambda user: user['name'])
    multiple_records(mypooldb, lambda user: user[0])


@pytest.mark.mysql
def test_mysql_multiple_records_error(mydb, mypooldb):
    from .test_db import multiple_records_error
    for db in (mydb, mypooldb):
        multiple_records_error(db)


@pytest.mark.mysql
def test_tuple_cursor(mydb_persist):
    with mydb_persist.cursor as cursor:
        user = mydb_persist.user.by_name.get(cursor, name='User 4')
        assert user[0] == 'user.4@example.com'
        with pytest.raises(TypeError):
            user['email']
        cursor.rollback()


@pytest.mark.mysql
def test_dict_cursor(mydb):
    with mydb.cursor as cursor:
        user = mydb.user.by_name.get(cursor, name='User 3')
        assert user['email'] == 'user.3@example.com'
        with pytest.raises(KeyError):
            user[0]
        cursor.rollback()


@pytest.mark.mysql
def test_many(mydb, mypooldb):
    from .test_db import many
    for db in (mydb, mypooldb):
        many(db)


@pytest.mark.mysql
def test_many_default(mydb):
    with mydb.cursor as cursor:
        users = mydb.users.all.many(cursor)
        assert len(users) == 1
        users = mydb.users.all.next(cursor)
        assert len(users) == 1

        users = mydb.users.all.many(cursor, 2, test='test')
        assert len(users) == 2
        users = mydb.users.all.next(cursor, 2)
        assert len(users) == 2

        users = mydb.users.all.many(cursor, test='test', size=2)
        assert len(users) == 2
        users = mydb.users.all.next(cursor, size=2)
        assert len(users) == 2

        users = cursor.users.all.many()
        assert len(users) == 1
        users = cursor.users.all.next()
        assert len(users) == 1

        users = cursor.users.all.many(2, test='test')
        assert len(users) == 2
        users = cursor.users.all.next(2)
        assert len(users) == 2

        users = cursor.users.all.many(test='test', size=2)
        assert len(users) == 2
        users = cursor.users.all.next(size=2)
        assert len(users) == 2
