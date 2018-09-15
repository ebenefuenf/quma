import pytest

from . import util
from ..exc import (
    DoesNotExistError,
    MultipleRecordsError,
)
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
                      name='Test User',
                      email='test.user@example.com',
                      city='Test City')
        cursor.commit()
        pgdb.user.remove(cursor, name='Test User')
        cursor.commit()
    finally:
        cursor.close()


@pytest.mark.postgres
def test_commit(pgdb, pgpooldb):
    for db in (pgdb, pgpooldb):
        with pgdb.cursor as cursor:
            pgdb.user.add(cursor,
                          name='Test User',
                          email='test.user@example.com',
                          city='Test City')
        with pgdb.cursor as cursor:
            with pytest.raises(DoesNotExistError):
                pgdb.user.by_name.get(cursor, name='Test User')

        with pgdb.cursor as cursor:
            pgdb.user.add(cursor,
                          name='Test User',
                          email='test.user@example.com',
                          city='Test City')
            cursor.commit()

        cursor = pgdb.cursor()
        pgdb.user.by_name.get(cursor, name='Test User')
        pgdb.user.remove(cursor, name='Test User')
        cursor.commit()
        with pytest.raises(DoesNotExistError):
            pgdb.user.by_name.get(cursor, name='Test User')
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
                      name='Test User',
                      email='test.user@example.com',
                      city='Test City')
        # no explicit commit
    with pgdb.cursor as cursor:
        assert cursor.get_conn_attr('autocommit') is False
        user = pgdb.user.by_name.get(cursor, name='Test User')
    assert user.email == 'test.user@example.com'


@pytest.mark.postgres
def test_rollback(pgdb):
    cursor = pgdb.cursor()
    pgdb.user.add(cursor,
                  name='Test User',
                  email='test.user@example.com',
                  city='Test City')
    pgdb.user.by_name.get(cursor, name='Test User')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        pgdb.user.by_name.get(cursor, name='Test User')
    cursor.close()


@pytest.mark.postgres
def test_changeling_cursor(pgdb):
    with pgdb.cursor as cursor:
        user = pgdb.user.by_name.get(cursor, name='User 3')
        assert user[0] == 'user.3@example.com'
        assert user['email'] == 'user.3@example.com'
        assert user.email == 'user.3@example.com'
        with pytest.raises(AttributeError):
            user.wrong_attr
        assert 'email' in user.keys()


@pytest.mark.postgres
def test_no_changeling_cursor(pgdb_persist):
    # pgdb_persist does not use the changeling factory
    with pgdb_persist.cursor as cursor:
        user = pgdb_persist.user.by_name.get(cursor, name='User 3')
        assert user[0] == 'user.3@example.com'
        assert user['email'] == 'user.3@example.com'
        with pytest.raises(AttributeError):
            user.email
        cursor.rollback()


@pytest.mark.postgres
def test_multiple_records(pgdb):
    with pgdb.cursor as cursor:
        users = pgdb.users.by_city(cursor, city='City A')
        assert len(users) == 2
        for user in users:
            assert user.name in ('User 1', 'User 2')


@pytest.mark.postgres
def test_multiple_records_error(pgdb):
    with pgdb.cursor as cursor:
        with pytest.raises(MultipleRecordsError):
            pgdb.user.by_city.get(cursor, city='City A')


@pytest.mark.postgres
def test_many(pgdb):
    with pgdb.cursor as cursor:
        users = pgdb.users.all.many(cursor, 2)
        assert len(users) == 2
        users = pgdb.users.all.next(cursor, 1)
        assert len(users) == 1
        users = pgdb.users.all.next(cursor, 1)
        assert len(users) == 1
        users = pgdb.users.all.next(cursor, 1)
        assert len(users) == 0


@pytest.mark.postgres
def test_many_default(pgdb):
    with pgdb.cursor as cursor:
        users = pgdb.users.all.many(cursor)
        assert len(users) == 1
        users = pgdb.users.all.next(cursor)
        assert len(users) == 1

        users = pgdb.users.all.many(cursor, 2, test='test')
        assert len(users) == 2
        users = pgdb.users.all.next(cursor, 2)
        assert len(users) == 2

        users = pgdb.users.all.many(cursor, test='test', size=2)
        assert len(users) == 2
        users = pgdb.users.all.next(cursor, size=2)
        assert len(users) == 2

        users = pgdb.users.all.many(cursor, 2, 'test')
        assert len(users) == 2
        users = pgdb.users.all.next(cursor)
        assert len(users) == 1
