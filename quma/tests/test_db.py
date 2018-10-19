import platform
import sqlite3
from unittest import mock

import pytest

from . import util
from .. import (
    Database,
    Namespace,
)
from .. import cursor as cursor_
from .. import (
    database,
    query,
    script,
)


def test_init(db):
    assert '__root__' in db.namespaces
    assert 'addresses' in db.namespaces
    assert 'users' in db.namespaces


def conn_attr(db, attr, defval, setval):
    with db.cursor as c:
        assert getattr(c.raw_conn, attr) == defval
        assert c.get_conn_attr(attr) == getattr(c.raw_conn, attr)
        c.set_conn_attr(attr, setval)
        assert getattr(c.raw_conn, attr) == setval
        assert c.get_conn_attr(attr) is getattr(c.raw_conn, attr)


def test_conn_attr(db):
    conn_attr(db, 'isolation_level', 'DEFERRED', 'EXCLUSIVE')


def test_failing_init(db):
    with pytest.raises(ValueError) as e:
        Database(1, 2, 3)
    assert 'Max number' in str(e)


def test_failing_connect():
    with pytest.raises(ValueError) as e:
        database.connect('sqlite+wrong-scheme:///:memory:')
    assert str(e.value).startswith('Wrong scheme')
    with pytest.raises(ValueError) as e:
        database.connect('sqlite:///')
    assert str(e.value).startswith('Required database path')


def test_namespace(db):
    assert type(db.addresses) is Namespace
    assert isinstance(db.users, Namespace)
    with pytest.raises(AttributeError) as e:
        db.nonexistent
    assert str(e.value).startswith('Namespace or Root method')
    with db.cursor as cursor:
        with pytest.raises(AttributeError) as e:
            cursor.nonexistent
        assert str(e.value).startswith('Namespace, Root method, or')


def test_root_attr(db):
    assert isinstance(db.get_users, script.Script)
    with db().cursor as cursor:
        assert len(db.get_users(cursor)) == 7
        assert len(cursor.get_users()) == 7
        assert len(db.root.get_users(cursor)) == 7
        assert len(cursor.root.get_users()) == 7
        assert db.get_test(cursor) == 'Test'
        assert cursor.get_test() == 'Test'
        assert db.root.get_test(cursor) == 'Test'
        assert cursor.root.get_test() == 'Test'
        with pytest.raises(AttributeError):
            db.get_faulty_test(cursor)
        with pytest.raises(AttributeError):
            db.root.get_faulty_test(cursor)


def test_script(db):
    assert str(db.users.all).startswith('SELECT id, name, email')
    with db.cursor as cursor:
        assert str(cursor.users.all).startswith('SELECT id, name, email')


def cursor(db):
    with db().cursor as cursor:
        assert type(cursor) is cursor_.Cursor
        assert len(db.users.all(cursor)) == 7
        assert len(cursor.users.all()) == 7
        with pytest.raises(AttributeError):
            cursor.raw_cursor.non_existent_attr


def test_cursor(db):
    cursor(db)


def test_carrier(dbfile):
    carrier = type('Carrier', (), {})
    with dbfile(carrier).cursor as cursor:
        assert len(dbfile.users.all(cursor)) == 7
        assert len(cursor.users.all()) == 7
        rc = cursor.raw_conn
    assert hasattr(carrier, '__quma_conn__')
    with dbfile(carrier).cursor as cursor:
        assert rc is cursor.raw_conn
    cursor.close()
    assert not hasattr(carrier, '__quma_conn__')
    with dbfile(carrier).cursor as cursor:
        assert rc is not cursor.raw_conn
        rc = cursor.raw_conn
    assert hasattr(carrier, '__quma_conn__')
    with dbfile(carrier).cursor as cursor:
        assert rc is cursor.raw_conn
    dbfile.release(carrier)
    assert not hasattr(carrier, '__quma_conn__')


def test_custom_namespace(db):
    with db.cursor as cursor:
        assert type(db.users).__module__ == 'quma.mapping.users'
        assert type(cursor.users.namespace).__module__ == 'quma.mapping.users'
        assert type(db.users).__name__ == 'Users'
        assert type(cursor.users.namespace).__name__ == 'Users'
        assert db.users.get_test(cursor) == 'Test'
        # Test the namespace alias
        assert db.user.get_test(cursor) == 'Test'


def cursor_call(db):
    cursor = db.cursor()
    try:
        db.user.add(cursor,
                    id=8,
                    name='Test User 1',
                    email='test.user@example.com',
                    city='Test City')
        cursor.user.add(id=9,
                        name='Test User 2',
                        email='test.user@example.com',
                        city='Test City')
        cursor.commit()
        db.user.remove(cursor, name='Test User 1')
        cursor.user.remove(name='Test User 2')
        cursor.commit()
    finally:
        cursor.close()


def test_cursor_call(db):
    cursor_call(db)


def first(db):
    cursor = db.cursor()
    assert cursor.users.all().first()['name'] == 'User 1'
    assert db.users.all(cursor).first()['name'] == 'User 1'
    assert cursor.users.none().first() is None
    assert db.users.none(cursor).first() is None
    cursor.close()


def test_first(db):
    first(db)


def value(db):
    cursor = db.cursor()
    assert cursor.users.by_email('user.1@example.com', 1).value() == 'User 1'
    assert cursor.users.by_email('user.1@example.com', 1).value(1) == 'City A'
    assert db.users.by_email(cursor,
                             'user.2@example.com',
                             1).value() == 'User 2'
    assert db.users.by_email(cursor,
                             'user.2@example.com',
                             1).value(1) == 'City A'
    cursor.close()


def test_value(db):
    value(db)


def value_str(db):
    cursor = db.cursor()
    assert cursor.users.by_name(name='User 1').value('city') == 'City A'
    assert db.users.by_name(cursor, name='User 1').value('city') == 'City A'
    cursor.close()


def test_value_str(db):
    value_str(db)


def query_attr(db):
    cursor = db.cursor()
    q = cursor.user.add(id=8,
                        name='Test User',
                        email='test.user@example.com',
                        city='Test City').run()
    assert q.lastrowid is not None
    cursor.close()


def test_query_attr(db):
    query_attr(db)


def getitem(db):
    cursor = db.cursor()
    assert cursor.users.all()[1]['name'] == 'User 2'
    result = db.users.all(cursor)
    assert result[3]['email'] == 'user.4@example.com'
    cursor.close()


def test_getitem(db):
    getitem(db)


def tbool(db):
    cursor = db.cursor()
    assert cursor.users.all()
    assert not cursor.users.none()
    cursor.close()


def test_bool(db):
    tbool(db)


def commit(db):
    with db.cursor as cursor:
        for i in range(8, 16, 2):
            db.user.add(cursor,
                        id=i,
                        name='Test User {}'.format(i),
                        email='test.user@example.com',
                        city='Test City').run()
            cursor.user.add(id=i + 1,
                            name='Test User {}'.format(i + 1),
                            email='test.user@example.com',
                            city='Test City').run()
    with db.cursor as cursor:
        with pytest.raises(db.DoesNotExistError):
            db.user.by_name(cursor, name='Test User 8').one()
        with pytest.raises(db.DoesNotExistError):
            db.user.by_name(cursor, name='Test User 11').one()

    with db.cursor as cursor:
        for i in range(8, 16, 2):
            db.user.add(cursor,
                        id=i,
                        name='Test User {}'.format(i),
                        email='test.user@example.com',
                        city='Test City').run()
            cursor.user.add(id=i + 1,
                            name='Test User {}'.format(i + 1),
                            email='test.user@example.com',
                            city='Test City').run()
        cursor.commit()

    cursor = db.cursor()
    for i in range(8, 16, 2):
        db.user.by_name(cursor, name='Test User {}'.format(i)).one()
        cursor.user.by_name(name='Test User {}'.format(i + 1)).one()
        db.user.remove(cursor, name='Test User {}'.format(i)).run()
        cursor.user.remove(name='Test User {}'.format(i + 1)).run()
    cursor.commit()
    with pytest.raises(db.DoesNotExistError):
        db.user.by_name(cursor, name='Test User 7').one()
    with pytest.raises(db.DoesNotExistError):
        db.user.by_name(cursor, name='Test User 8').one()
    cursor.close()


def test_commit(dbfile):
    commit(dbfile)


def test_contextcommit(dbcommit):
    with dbcommit.cursor as cursor:
        dbcommit.user.add(cursor,
                          id=8,
                          name='Test User',
                          email='test.user@example.com',
                          city='Test City').run()
    with dbcommit.cursor as cursor:
        user = dbcommit.user.by_name(cursor, name='Test User').one()
        assert user.email == 'test.user@example.com'


def autocommit(uri, sqldirs, insert_error, select_error):
    db = Database(uri, sqldirs)
    cursor = db.cursor(autocommit=True)
    with pytest.raises(insert_error):
        cursor.execute("INSERT INTO test (name) VALUES ('Test 1');")
    cursor.execute('CREATE TABLE test (name VARCHAR(10));')
    cursor.close()
    db = Database(uri, sqldirs)
    with db.cursor as cursor:
        cursor.execute("INSERT INTO test (name) VALUES ('Test 1');")
        cursor.execute("INSERT INTO test (name) VALUES ('Test 2');")
    db = Database(uri, sqldirs)
    with db.cursor as cursor:
        cursor.execute('SELECT * FROM test;')
        assert len(cursor.fetchall()) == 0
    db = Database(uri, sqldirs)
    with db(autocommit=True).cursor as cursor:
        cursor.execute("INSERT INTO test (name) VALUES ('Test 1');")
        cursor.execute("INSERT INTO test (name) VALUES ('Test 2');")
    db = Database(uri, sqldirs)
    with db.cursor as cursor:
        cursor.execute('SELECT * FROM test;')
        assert len(cursor.fetchall()) == 2
    db = Database(uri, sqldirs)
    cursor = db.cursor()
    cursor.execute("INSERT INTO test (name) VALUES ('Test 3');")
    cursor.execute("INSERT INTO test (name) VALUES ('Test 4');")
    cursor.close()
    db = Database(uri, sqldirs)
    cursor = db.cursor()
    cursor.execute('SELECT * FROM test;')
    assert len(cursor.fetchall()) == 2
    cursor.close()
    db = Database(uri, sqldirs)
    cursor = db.cursor(autocommit=True)
    cursor.execute("INSERT INTO test (name) VALUES ('Test 3');")
    cursor.execute("INSERT INTO test (name) VALUES ('Test 4');")
    cursor.close()
    db = Database(uri, sqldirs)
    cursor = db.cursor()
    cursor.execute('SELECT * FROM test;')
    assert len(cursor.fetchall()) == 4
    cursor.close()


def test_autocommit(qmark_sqldirs):
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI, qmark_sqldirs)
    with db.cursor as cursor:
        cursor.execute('CREATE TABLE test (name);')
        cursor.execute("INSERT INTO test (name) VALUES ('Test 1');")
        cursor.execute("INSERT INTO test (name) VALUES ('Test 2');")
    db = Database(util.SQLITE_URI, qmark_sqldirs)
    with db(autocommit=True).cursor as cursor:
        cursor.execute("INSERT INTO test (name) VALUES ('Test 1');")
        cursor.execute("INSERT INTO test (name) VALUES ('Test 2');")
    db = Database(util.SQLITE_URI, qmark_sqldirs)
    with db().cursor as cursor:
        cursor.execute('SELECT * FROM test;')
        assert len(cursor.fetchall()) == 2


def rollback(db):
    cursor = db.cursor()
    db.user.add(cursor,
                id=8,
                name='Test User',
                email='test.user@example.com',
                city='Test City').run()
    db.user.by_name(cursor, name='Test User').one()
    cursor.rollback()
    with pytest.raises(db.DoesNotExistError):
        db.user.by_name(cursor, name='Test User').one()
    cursor.close()


def test_rollback(dbfile):
    rollback(dbfile)


def test_overwrite_script_class(pyformat_sqldirs):
    class MyScript(script.Script):
        def the_test(self):
            return 'Test'
    db = Database(util.SQLITE_MEMORY,
                  pyformat_sqldirs,
                  script_factory=MyScript)
    assert db.user.all.the_test() == 'Test'


def changeling_cursor(db):
    with db.cursor as cursor:
        user = db.user.by_name(cursor, name='User 3').one()
        assert user[0] == 'user.3@example.com'
        assert user['email'] == 'user.3@example.com'
        assert user.email == 'user.3@example.com'
        user.email = 'test@example.com'
        assert user.email == 'test@example.com'
        with pytest.raises(AttributeError):
            user.wrong_attr
        assert 'email' in user._keys()


def test_changeling_cursor(db):
    changeling_cursor(db)


def test_changeling_cursor_hidden_members(db):
    with db.cursor as cursor:
        user = db.user.by_name(cursor, name='User 1').one()
        assert user.keys == 'the keys'
        assert set(user._keys()) == set(['email', 'city', 'keys'])


def no_changeling_cursor(pgdb_persist, getter, error):
    # pgdb_persist does not use the changeling factory
    with pgdb_persist.cursor as cursor:
        user = pgdb_persist.user.by_name(cursor, name='User 3').one()
        assert user[0] == 'user.3@example.com'
        with pytest.raises(error):
            getter(user)
        cursor.rollback()


def test_no_changeling_cursor(db_no_changeling):
    no_changeling_cursor(db_no_changeling,
                         lambda user: user['email'],
                         TypeError)
    no_changeling_cursor(db_no_changeling,
                         lambda user: user.email,
                         AttributeError)


def test_pypy_changeling_init(qmark_sqldirs):
    with mock.patch('quma.provider.sqlite.PLATFORM', 'PyPy'):
        db = Database(util.SQLITE_MEMORY,
                      sqldirs=qmark_sqldirs,
                      persist=True,
                      changeling=True)
        db.execute(util.CREATE_USERS)
        db.execute(util.INSERT_USERS)
        if platform.python_implementation() == 'PyPy':
            with db.cursor as cursor:
                cursor.users.all().first()
        else:
            with pytest.raises(TypeError):
                with db.cursor as cursor:
                    cursor.users.all().first()


def test_qmark_script(db):
    with db.cursor as cursor:
        user = db.user.by_email(cursor, 'user.3@example.com', 1).one()
        assert user[0] == 'User 3'
        assert user['name'] == 'User 3'
        assert user.name == 'User 3'
        with pytest.raises(AttributeError):
            user.wrong_attr
        assert 'name' in user.keys()


def test_template_script(db):
    with db.cursor as cursor:
        user = db.user.by_name_tmpl(cursor, name='User 1').one()
        assert user.intro == "I'm User 1"
        user = db.user.by_name_tmpl(cursor, name='User 2').one()
        assert user.intro == "I'm not User 1"

        tmpl = script.Template
        script.Template = None
        with pytest.raises(ImportError) as e:
            db.user.by_name_tmpl(cursor, name='User 1').one()
        assert str(e.value).startswith('To use templates')
        script.Template = tmpl


def test_dict_callback(dbdictcb, carrier):
    db = dbdictcb

    def dict_callback(carrier, params):
        return {'name': 'User 3'}

    with db(carrier).cursor as c:
        user = db.user.by_name(c).one()
        assert user['city'] == 'City A'
        user = db.user.by_name(c, prepare_params=dict_callback).one()
        assert user['city'] == 'City B'


def test_seq_callback(dbseqcb, carrier):
    db = dbseqcb

    def seq_callback(carrier, params):
        return ['user.3@example.com']

    with db(carrier).cursor as c:
        user = db.user.by_email(c, 1).one()
        assert user['city'] == 'City A'
        user = db.user.by_email(c, 1, prepare_params=seq_callback).one()
        assert user['city'] == 'City B'


def multiple_records(db, getter):
    with db.cursor as cursor:
        # normal iteration
        users = db.users.by_city(cursor, city='City A')
        assert type(users) is query.Query
        i = 0
        for user in users:
            assert getter(user) in ('User 1', 'User 2')
            i += 1
        assert i == 2

        # the .all() method
        users = db.users.by_city(cursor, city='City A').all()
        assert type(users) is list or type(users) is tuple
        for user in users:
            assert getter(user) in ('User 1', 'User 2')
        assert len(users) == 2

        # cast the iterator to a list
        if platform.python_implementation() == 'CPython' or \
           db.conn.__class__.__module__ != 'quma.provider.sqlite':
            # TODO: the cast to list does only work in CPython for all
            # dricers. In PyPy using the sqlite3 driver the fetch call
            # in Query.__iter__ returns an empty list.
            #
            # The same behavior was present in CPython when we didn't
            # return a generator but iterated over the fetch result
            # and yielded the rows. It is only with the SQLite driver.
            assert len(list(db.users.by_city(cursor, city='City A'))) == 2


def test_multiple_records(dbfile):
    multiple_records(dbfile, lambda user: user.name)


def multiple_records_error(db):
    with db.cursor as cursor:
        with pytest.raises(db.MultipleRowsError):
            db.user.by_city(cursor, city='City A').one()


def test_multiple_records_error(dbfile):
    multiple_records_error(dbfile)


def count(db):
    cursor = db.cursor()
    assert cursor.users.all().count() == 7
    assert db.users.all(cursor).count() == 7
    assert len(cursor.users.all()) == 7
    assert len(db.users.all(cursor)) == 7
    cursor.close()


def test_count(db):
    count(db)


def rowcount(db):
    cur = db.cursor()
    assert db.user.add(
                    cur,
                    id=8,
                    name='Test User 1',
                    email='test.user@example.com',
                    city='Test City').count() == 1
    assert cur.user.add(
                    id=9,
                    name='Test User 2',
                    email='test.user@example.com',
                    city='Test City').count() == 1
    assert len(db.user.add(
                    cur,
                    id=10,
                    name='Test User 3',
                    email='test.user@example.com',
                    city='Test City')) == 1
    assert len(cur.user.add(
                    id=11,
                    name='Test User 4',
                    email='test.user@example.com',
                    city='Test City')) == 1
    assert db.users.update(cur,
                           email='test1@example.com',
                           city='Test City').count() == 4
    assert cur.users.update(email='test2@example.com',
                            city='Test City').count() == 4
    assert len(db.users.update(cur,
                               email='test3@example.com',
                               city='Test City')) == 4
    assert len(cur.users.update(email='test4@example.com',
                                city='Test City')) == 4
    assert db.user.remove(cur, name='Test User 1').count() == 1
    assert cur.user.remove(name='Test User 2').count() == 1
    assert len(db.user.remove(cur, name='Test User 3')) == 1
    assert len(cur.user.remove(name='Test User 4')) == 1
    cur.commit()
    cur.close()


def exists(db):
    with db.cursor as cursor:
        assert cursor.users.all().exists()
        assert not cursor.users.none().exists()


def test_exists(dbfile):
    exists(dbfile)


def query_cache(db):
    with db.cursor as cursor:
        users = cursor.users.all()
        assert users._has_been_executed is False
        assert users._result_cache is None
        i = 0
        for user in users:
            assert users._has_been_executed is True
            i += 1
        assert users._result_cache is not None
        assert i == 7
        assert len(users.all()) == 7
        assert users.first() is not None
        assert users.exists()
        with pytest.raises(db.MultipleRowsError):
            users.one()
        users.run()
        assert users._has_been_executed is True
        assert users._result_cache is None
        assert users.first() is not None
        assert users._result_cache is not None


def test_query_cache(db):
    query_cache(db)


def many(db):
    with db.cursor as cursor:
        users = db.users.all(cursor).many()
        assert len(users.get(2)) == 2
        assert len(users.get(size=3)) == 3
        assert len(users.get(size=1)) == 1
        assert len(users.get()) == 1
        assert len(users.get(size=4)) == 0

        users = cursor.users.all().many()
        assert len(users.get(2)) == 2
        assert len(users.get(size=3)) == 3
        assert len(users.get(size=1)) == 1
        assert len(users.get()) == 1
        assert len(users.get(size=4)) == 0


def test_many(dbfile):
    many(dbfile)


def many_default(db):
    with db.cursor as cursor:
        users = db.users.all(cursor).many()
        i = 0
        while len(users.get()) == 1:
            i += 1
        assert i == 7

        users = cursor.users.all().many()
        i = 0
        while len(users.get()) == 1:
            i += 1
        assert i == 7


def test_many_default(dbfile):
    many_default(dbfile)


def test_generator(db):
    def users_generator():
        with db.cursor as cur:
            manyusers = cur.users.all().many()
            batch = manyusers.get(3)
            while len(batch):
                for result in batch:
                    yield result
                batch = manyusers.get(2)

    assert len(list(users_generator())) == 7


def unbunch(db):
    with db.cursor as cur:
        i = 0
        for user in cur.users.all().unbunch(3):
            i += 1
        assert i == 7


def test_unbunch(db):
    unbunch(db)


def test_shadowing(db, dbshadow):
    with db.cursor as cursor:
        assert len(dbshadow.get_users(cursor)) == 7
        assert db.get_test(cursor) == 'Test'
        assert db.get_city(cursor).one().name == 'Shadowed City'
        assert db.addresses.by_zip(cursor).one().address == 'Shadowed Address'

    with dbshadow.cursor as cursor:
        # root script from shadowed dir
        assert len(dbshadow.get_users(cursor)) == 7
        assert len(cursor.get_users()) == 7
        # masking root script
        assert dbshadow.get_city(cursor).one().name == 'Masking City'
        assert cursor.get_city().one().name == 'Masking City'
        # root script from masking dir
        assert len(dbshadow.get_trees(cursor)) == 2
        assert len(cursor.get_trees()) == 2
        # root method from shadowed dir
        assert dbshadow.get_shadowed_test(cursor) == 'Shadowed Test'
        assert cursor.get_shadowed_test() == 'Shadowed Test'
        # masking root method
        assert dbshadow.get_test(cursor) == 'Masking Test'
        assert cursor.get_test() == 'Masking Test'
        # namespace script from shadowed dir
        user = dbshadow.addresses.by_user(cursor).one()
        assert user.address == 'Shadowed Address'
        user = cursor.addresses.by_user().one()
        assert user.address == 'Shadowed Address'
        # namespace script from masking dir
        assert dbshadow.addresses.get_tree(cursor).one().name == 'Masking Oak'
        assert cursor.addresses.get_tree().one().name == 'Masking Oak'
        # masking namespace script
        address = dbshadow.addresses.by_zip(cursor).one().address
        assert address == 'Masking Address'
        address = cursor.addresses.by_zip().one().address
        assert address == 'Masking Address'


def test_show_parameter(dbshow):
    import sys
    tmp = sys.stdout
    sys.stdout = type('S', (), {})
    sql = {}

    def write(s):
        sql['sql'] = s

    sys.stdout.write = write
    with dbshow.cursor as cursor:
        dbshow.user.by_name(cursor, name='User 1').one()
        assert 'SELECT email, city' in sql['sql']
        cursor.user.by_city(city='City 1').first()
        assert 'SELECT name, email' in sql['sql']

    sys.stdout = tmp


def test_caching(db, dbcache):
    with db.cursor as cursor:
        assert len(db.user._scripts) == 0
    with dbcache.cursor as cursor:
        user = dbcache.user.by_name(cursor, name='User 1').one()
        assert user.city == 'City A'
        assert dbcache.user.get_test(cursor) == 'Test'
        assert len(dbcache.user._scripts) >= 0

        user = cursor.user.by_name(name='User 1').one()
        assert user.city == 'City A'
        assert cursor.user.get_test() == 'Test'
        assert len(cursor.user._scripts) >= 0


def test_close(db):
    from .. import provider
    assert type(db.conn) is provider.sqlite.Connection
    db.close()
    assert db.conn is None


def execute(db, error):
    db.execute('CREATE TABLE test (test int);')
    result = db.execute('DROP TABLE test;')
    assert result is None
    result = db.execute('SELECT * FROM users')
    assert len(result) > 0
    with pytest.raises(error):
        db.execute('SELECT * FRO')

    with db.cursor as cursor:
        cursor.execute('SELECT * FROM users')
        assert len(cursor.fetchall()) > 0


def test_execute(db):
    execute(db, sqlite3.OperationalError)
