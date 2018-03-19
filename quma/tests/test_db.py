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


def test_init(db):
    assert 'addresses' in db.namespaces
    assert 'users' in db.namespaces


def test_failing_init(db):
    with pytest.raises(ValueError) as e:
        Database(1, 2, 3)
    assert 'Max number' in str(e)


def test_namespace(db):
    assert type(db.addresses) is Namespace
    assert isinstance(db.users, Namespace)


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
        assert db.users.get_hans(cursor) == 'Hans'
        # Test the namespace alias
        assert db.user.get_hans(cursor) == 'Hans'


def test_cursor_call(db):
    cursor = db.cursor()
    try:
        db.user.add(cursor,
                    name='Anneliese Günthner',
                    email='anneliese.guenthner@example.com',
                    city='Sassanfahrt')
        cursor.commit()
        db.user.remove(cursor, name='Anneliese Günthner')
        cursor.commit()
    finally:
        cursor.close()


def test_commit(db):
    with db.cursor as cursor:
        db.user.add(cursor,
                    name='hans',
                    email='hans@example.com',
                    city='city')
    with db.cursor as cursor:
        with pytest.raises(DoesNotExistError):
            db.user.by_name.get(cursor, name='hans')

    with db.cursor as cursor:
        db.user.add(cursor,
                    name='hans',
                    email='hans@example.com',
                    city='city')
        cursor.commit()

    cursor = db.cursor()
    db.user.by_name.get(cursor, name='hans')
    db.user.remove(cursor, name='hans')
    cursor.commit()
    with pytest.raises(DoesNotExistError):
        db.user.by_name.get(cursor, name='hans')
    cursor.close()


def test_rollback(db):
    cursor = db.cursor()
    db.user.add(cursor,
                name='hans',
                email='hans@example.com',
                city='city')
    db.user.by_name.get(cursor, name='hans')
    cursor.rollback()
    with pytest.raises(DoesNotExistError):
        db.user.by_name.get(cursor, name='hans')
    cursor.close()


def test_overwrite_query_class(pyformat_sqldirs):
    class MyQuery(Query):
        def the_test(self):
            return 'Hans Karl'
    db = Database(util.PG_POOL_URI, pyformat_sqldirs, query_factory=MyQuery)
    assert db.user.all.the_test() == 'Hans Karl'


def test_changeling_cursor(db):
    with db.cursor as cursor:
        hans = db.user.by_name.get(cursor, name='Franz Görtler')
        assert hans[0] == 'franz.goertler@example.com'
        assert hans['email'] == 'franz.goertler@example.com'
        assert hans.email == 'franz.goertler@example.com'
        with pytest.raises(AttributeError):
            hans.wrong_attr
        assert 'email' in hans.keys()


def test_qmark_query(db):
    with db.cursor as cursor:
        emil = db.user.by_email.get(cursor, 'emil.jaeger@example.com', 1)
        assert emil[0] == 'Emil Jäger'
        assert emil['name'] == 'Emil Jäger'
        assert emil.name == 'Emil Jäger'
        with pytest.raises(AttributeError):
            emil.wrong_attr
        assert 'name' in emil.keys()


def test_dict_callback(dbdictcb, carrier1):
    db = dbdictcb

    def dict_callback(carrier, params):
        return {'name': 'Hans Karl'}

    with db(carrier1).cursor as c:
        user = db.user.by_name.get(c)
        assert user['city'] == 'Oberhaid'
        user = db.user.by_name.get(c, init_params=dict_callback)
        assert user['city'] == 'Staffelbach'


def test_seq_callback(dbseqcb, carrier1):
    db = dbseqcb

    def seq_callback(carrier, params):
        return ['hans.karl@example.com']

    with db(carrier1).cursor as c:
        user = db.user.by_email.get(c, 1)
        assert user['city'] == 'Oberhaid'
        user = db.user.by_email.get(c, 1, init_params=seq_callback)
        assert user['city'] == 'Staffelbach'
