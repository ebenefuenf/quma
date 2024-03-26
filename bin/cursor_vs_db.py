import os
import sys
from timeit import Timer

import quma
from quma.tests import util

loops = int(sys.argv[1]) if len(sys.argv) > 1 else 20000

here = os.path.dirname(__file__)
sql_path = os.path.join(here, "../quma/tests/fixtures/scripts/qmark")


def get_db():
    db = quma.Database(
        "sqlite:///:memory:",
        sql_path,
        persist=True,
        changeling=True,
        cache=True,
    )
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
            db.user.add(
                cursor,
                name="Test User",
                email="test.user@example.com",
                city="Test City",
            ).run()
            cursor.commit()

            db.user.by_name(cursor, name="User 1").one()
            db.user.by_name(cursor, name="Test User").one()
            db.users.all(cursor, name="Test User").first()
            db.users.all(cursor, name="Test User").all()
            db.user.remove(cursor, name="Test User").run()
            cursor.commit()


def cursor_namespaces():
    db = get_db()
    for _ in range(loops):
        with db.cursor as cursor:
            cursor.get_users()
            cursor.root.get_users()
            cursor.get_test()
            cursor.root.get_test()
            cursor.user.add(
                name="Test User",
                email="test.user@example.com",
                city="Test City",
            ).run()
            cursor.commit()

            cursor.user.by_name(name="User 1").one()
            cursor.user.by_name(name="Test User").one()
            cursor.users.all(name="Test User").first()
            cursor.users.all(name="Test User").all()
            cursor.user.remove(name="Test User").run()
            cursor.commit()


header = "\n{} loops:".format(loops)
print(header)
print("-" * (len(header) - 1))
t = Timer(lambda: db_namespaces())
print("db api:  ", t.timeit(number=1), "seconds")
t = Timer(lambda: cursor_namespaces())
print("cur api: ", t.timeit(number=1), "seconds")
