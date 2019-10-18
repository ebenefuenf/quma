import pytest

from . import util

try:
    import MySQLdb
except ImportError:
    MySQLdb = None


def setup_function(function):
    util.setup_mysql_db()


@pytest.mark.mysql
def test_conn_attr(mydb, mypooldb):
    from .test_db import conn_attr

    for db in (mydb, mypooldb):
        conn_attr(db, 'encoding', 'utf8', 'latin1')


@pytest.mark.mysql
def test_cursor(mydb, mypooldb):
    from .test_db import the_cursor

    for db in (mydb, mypooldb):
        the_cursor(db)


@pytest.mark.mysql
def test_carrier(mydb):
    from .test_db import carrier

    carrier(mydb)


@pytest.mark.mysql
def test_pool_carrier(mypooldb):
    from .test_db import pool_carrier

    pool_carrier(mypooldb)


@pytest.mark.mysql
def test_cursor_call(mydb, mypooldb):
    from .test_db import cursor_call

    for db in (mydb, mypooldb):
        cursor_call(db)


@pytest.mark.mysql
def test_count(mydb, mypooldb):
    from .test_db import count, rowcount

    for db in (mydb, mypooldb):
        count(db)
        rowcount(db)


@pytest.mark.mysql
def test_exists(mydb, mypooldb):
    from .test_db import exists

    for db in (mydb, mypooldb):
        exists(db)


@pytest.mark.mysql
def test_query_cache(mydb, mypooldb):
    from .test_db import query_cache

    for db in (mydb, mypooldb):
        query_cache(db)


@pytest.mark.mysql
def test_first(mydb_dict, mypooldb_dict):
    from .test_db import first

    for db in (mydb_dict, mypooldb_dict):
        first(db)


@pytest.mark.mysql
def test_value(mydb_persist, mypooldb):
    from .test_db import value

    for db in (mydb_persist, mypooldb):
        value(db)


@pytest.mark.mysql
def test_value_str(mydb_dict, mypooldb_dict):
    from .test_db import value_str

    for db in (mydb_dict, mypooldb_dict):
        value_str(db)


@pytest.mark.mysql
def test_query_attr(mydb, mypooldb_dict):
    from .test_db import query_attr

    for db in (mydb, mypooldb_dict):
        query_attr(db)


@pytest.mark.mysql
def test_get_item(mydb_dict, mypooldb_dict):
    from .test_db import get_item

    for db in (mydb_dict, mypooldb_dict):
        get_item(db)


@pytest.mark.mysql
def test_bool(mydb, mypooldb_dict):
    from .test_db import tbool

    for db in (mydb, mypooldb_dict):
        tbool(db)


@pytest.mark.mysql
def test_commit(mydb, mypooldb):
    from .test_db import commit

    for db in (mydb, mypooldb):
        commit(db)


@pytest.mark.mysql
def test_autocommit(pyformat_sqldirs):
    from .test_db import autocommit

    autocommit(
        util.MYSQL_URI,
        pyformat_sqldirs,
        MySQLdb.ProgrammingError,
        MySQLdb.OperationalError,
    )


@pytest.mark.mysql
def test_autocommit_pool(pyformat_sqldirs):
    from .test_db import autocommit

    autocommit(
        util.MYSQL_POOL_URI,
        pyformat_sqldirs,
        MySQLdb.ProgrammingError,
        MySQLdb.OperationalError,
    )


@pytest.mark.mysql
def test_rollback(mydb, mypooldb):
    from .test_db import rollback

    for db in (mydb, mypooldb):
        rollback(db)


@pytest.mark.mysql
def test_multiple_records(mydb_dict, mypooldb):
    from .test_db import multiple_records

    multiple_records(mydb_dict, lambda user: user['name'])
    multiple_records(mypooldb, lambda user: user[0])


@pytest.mark.mysql
def test_multiple_records_error(mydb, mypooldb):
    from .test_db import multiple_records_error

    for db in (mydb, mypooldb):
        multiple_records_error(db)


@pytest.mark.mysql
def test_tuple_cursor(mydb_persist, mypooldb):
    for db in (mydb_persist, mypooldb):
        with db.cursor as cursor:
            user = db.user.by_name(cursor, name='User 4').one()
            assert user[0] == 'user.4@example.com'
            with pytest.raises(TypeError):
                user['email']
            cursor.rollback()


@pytest.mark.mysql
def test_dict_cursor(mydb_dict, mypooldb_dict):
    for db in (mydb_dict, mypooldb_dict):
        with db.cursor as cursor:
            user = db.user.by_name(cursor, name='User 3').one()
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
def test_many_default(mydb, mypooldb):
    from .test_db import many_default

    for db in (mydb, mypooldb):
        many_default(db)


@pytest.mark.mysql
def test_unbunch(mydb, mypooldb):
    from .test_db import unbunch

    for db in (mydb, mypooldb):
        unbunch(db)


@pytest.mark.mysql
def test_execute(mydb, mypooldb_dict):
    from .test_db import execute

    for db in (mydb, mypooldb_dict):
        execute(db, MySQLdb.ProgrammingError)


@pytest.mark.mysql
def test_prepared_statement(mydb, mypooldb):
    for db in (mydb, mypooldb):
        with db.cursor as cur:
            cur.users.mysql_prepare().run()
            version = cur.query('SELECT VERSION();').value()
            if 'MariaDB' not in version:
                # Couldn't get the tests to run under MySQL 5
                return
            sql = "EXECUTE prep USING 'user.{}@example.com', 1;"
            for i in range(1, 5):
                q = cur.query(sql.format(i))
                assert q.value() == 'User {}'.format(i)
            cur.query('DEALLOCATE PREPARE prep;').run()


@pytest.mark.mysql
def test_cursor_query(mydb, mypooldb):
    sql = 'SELECT name, city FROM users WHERE email = %s AND 1 = %s;'
    for db in (mydb, mypooldb):
        with db.cursor as cur:
            q = cur.query(sql, 'user.1@example.com', 1)
            assert q.value() == 'User 1'


@pytest.mark.mysql
def test_echo_parameter(mydb_echo, mypooldb_echo):
    import sys

    tmp = sys.stdout
    sys.stdout = type('S', (), {})
    sql = {}

    def write(s):
        sql['sql'] = s

    sys.stdout.write = write

    for db in (mydb_echo, mypooldb_echo):
        with db.cursor as cursor:
            db.user.by_email(cursor, 'user.1@example.com', 1).one()
            assert (
                'SELECT name, city FROM users WHERE email = '
                "'user.1@example.com' AND 1 = 1;\n"
            ) == sql['sql']
    sys.stdout = tmp
