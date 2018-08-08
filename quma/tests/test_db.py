import pytest

from . import util
from .. import (
    Database,
    Namespace,
)
from ..exc import (
    DoesNotExistError,
    MultipleRecordsError,
)
from ..mapper import (
    Cursor,
    Query,
)


def test_init(db):
    assert '__root__' in db.namespaces
    assert 'addresses' in db.namespaces
    assert 'users' in db.namespaces


def test_failing_init(db):
    with pytest.raises(ValueError) as e:
        Database(1, 2, 3)
    assert 'Max number' in str(e)


def test_namespace(db):
    assert type(db.addresses) is Namespace
    assert isinstance(db.users, Namespace)


def test_root_attr(db):
    assert isinstance(db.get_users, Query)
    with db().cursor as cursor:
        assert len(db.get_users(cursor)) == 4


def test_query(db):
    assert str(db.users.all).startswith('SELECT * FROM users')


def test_cursor(db):
    with db().cursor as cursor:
        assert type(cursor) is Cursor
        assert len(db.users.all(cursor)) == 4


def test_custom_namespace(db):
    with db.cursor as cursor:
        assert type(db.users).__module__ == 'quma.mapping.users'
        assert type(db.users).__name__ == 'Users'
        assert db.users.get_test(cursor) == 'Test'
        # Test the namespace alias
        assert db.user.get_test(cursor) == 'Test'


def test_cursor_call(db):
    cursor = db.cursor()
    try:
        db.user.add(cursor,
                    name='Test User',
                    email='test.user@example.com',
                    city='Test City')
        cursor.commit()
        db.user.remove(cursor, name='Test User')
        cursor.commit()
    finally:
        cursor.close()


def test_commit(dbfile):
    with dbfile.cursor as cursor:
        dbfile.user.add(cursor,
                        name='Test User',
                        email='test.user@example.com',
                        city='Test City')
    with dbfile.cursor as cursor:
        with pytest.raises(DoesNotExistError):
            dbfile.user.by_name.get(cursor, name='Test User')

    with dbfile.cursor as cursor:
        dbfile.user.add(cursor,
                        name='Test User',
                        email='test.user@example.com',
                        city='Test City')
        cursor.commit()

    cursor = dbfile.cursor()
    dbfile.user.by_name.get(cursor, name='Test User')
    dbfile.user.remove(cursor, name='Test User')
    cursor.commit()
    with pytest.raises(DoesNotExistError):
        dbfile.user.by_name.get(cursor, name='Test User')
    cursor.close()


def test_rollback(db):
    cursor = db.cursor()
    db.user.add(cursor,
                name='Test User',
                email='test.user@example.com',
                city='Test City')
    db.user.by_name.get(cursor, name='Test User')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        db.user.by_name.get(cursor, name='Test User')
    cursor.close()


def test_overwrite_query_class(pyformat_sqldirs):
    class MyQuery(Query):
        def the_test(self):
            return 'Test'
    db = Database(util.PGSQL_POOL_URI, pyformat_sqldirs, query_factory=MyQuery)
    assert db.user.all.the_test() == 'Test'


def test_changeling_cursor(db):
    with db.cursor as cursor:
        user = db.user.by_name.get(cursor, name='User 2')
        assert user[0] == 'user.2@example.com'
        assert user['email'] == 'user.2@example.com'
        assert user.email == 'user.2@example.com'
        with pytest.raises(AttributeError):
            user.wrong_attr
        assert 'email' in user.keys()


def test_qmark_query(db):
    with db.cursor as cursor:
        user = db.user.by_email.get(cursor, 'user.3@example.com', 1)
        assert user[0] == 'User 3'
        assert user['name'] == 'User 3'
        assert user.name == 'User 3'
        with pytest.raises(AttributeError):
            user.wrong_attr
        assert 'name' in user.keys()


def test_dict_callback(dbdictcb, carrier):
    db = dbdictcb

    def dict_callback(carrier, params):
        return {'name': 'User 3'}

    with db(carrier).cursor as c:
        user = db.user.by_name.get(c)
        assert user['city'] == 'City A'
        user = db.user.by_name.get(c, init_params=dict_callback)
        assert user['city'] == 'City B'


def test_seq_callback(dbseqcb, carrier):
    db = dbseqcb

    def seq_callback(carrier, params):
        return ['user.3@example.com']

    with db(carrier).cursor as c:
        user = db.user.by_email.get(c, 1)
        assert user['city'] == 'City A'
        user = db.user.by_email.get(c, 1, init_params=seq_callback)
        assert user['city'] == 'City B'


def test_multiple_records(db):
    with db.cursor as cursor:
        users = db.users.by_city(cursor, city='City A')
        assert len(users) == 2
        for user in users:
            assert user.name in ('User 1', 'User 2')


def test_multiple_records_error(db):
    with db.cursor as cursor:
        with pytest.raises(MultipleRecordsError):
            db.user.by_city.get(cursor, city='City A')
