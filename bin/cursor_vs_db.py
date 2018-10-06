import os
from timeit import Timer

import quma
from quma.tests import util

loops = 20000

here = os.path.dirname(__file__)
sql_path = os.path.join(here, '../quma/tests/fixtures/queries/qmark')


def get_db():
    db = quma.Database('sqlite:///:memory:', sql_path,
                       persist=True, changeling=True, cache=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


def db_namespaces():
    db = get_db()
    for _ in range(loops):
        with db.cursor as cursor:
            db.get_users(cursor)
            db.root.get_users(cursor)
            db.get_test(cursor)
            db.root.get_test(cursor)
            db.user.add(cursor,
                        name='Test User',
                        email='test.user@example.com',
                        city='Test City')
            cursor.commit()
            db.user.by_name(cursor, name='User 1').get()
            db.user.by_name(cursor, name='Test User').one
            db.user.remove(cursor, name='Test User')
            cursor.commit()


def cursor_namespaces():
    db = get_db()
    for _ in range(loops):
        with db.cursor as cursor:
            cursor.get_users()
            cursor.root.get_users()
            cursor.get_test(cursor)
            cursor.root.get_users()
            cursor.root.get_test(cursor)
            cursor.user.add(name='Test User',
                            email='test.user@example.com',
                            city='Test City')
            cursor.commit()
            cursor.user.by_name(name='User 1').get()
            cursor.user.by_name(name='Test User').one
            cursor.user.remove(name='Test User')
            cursor.commit()


t = Timer(lambda: db_namespaces())
print(t.timeit(number=1))
t = Timer(lambda: cursor_namespaces())
print(t.timeit(number=1))
