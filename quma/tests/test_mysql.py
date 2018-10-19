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
        conn_attr(db, 'encoding', 'latin1', 'utf-8')


@pytest.mark.mysql
def test_cursor(mydb, mypooldb):
    from .test_db import cursor
    for db in (mydb, mypooldb):
        cursor(db)


@pytest.mark.mysql
def test_cursor_call(mydb, mypooldb):
    from .test_db import cursor_call
    for db in (mydb, mypooldb):
        cursor_call(db)


@pytest.mark.mysql
def test_count(mydb, mypooldb):
    from .test_db import (
        count,
        rowcount,
    )
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
def test_first(mydb, mypooldbdict):
    from .test_db import first
    for db in (mydb, mypooldbdict):
        first(db)


@pytest.mark.mysql
def test_value(mydbpersist, mypooldb):
    from .test_db import value
    for db in (mydbpersist, mypooldb):
        value(db)


@pytest.mark.mysql
def test_value_str(mydb, mypooldbdict):
    from .test_db import value_str
    for db in (mydb, mypooldbdict):
        value_str(db)


@pytest.mark.mysql
def test_query_attr(mydb, mypooldbdict):
    from .test_db import query_attr
    for db in (mydb, mypooldbdict):
        query_attr(db)


@pytest.mark.mysql
def test_getitem(mydb, mypooldbdict):
    from .test_db import getitem
    for db in (mydb, mypooldbdict):
        getitem(db)


@pytest.mark.mysql
def test_bool(mydb, mypooldbdict):
    from .test_db import tbool
    for db in (mydb, mypooldbdict):
        tbool(db)


@pytest.mark.mysql
def test_commit(mydb, mypooldb):
    from .test_db import commit
    for db in (mydb, mypooldb):
        commit(db)


@pytest.mark.mysql
def test_autocommit(pyformat_sqldirs):
    from .test_db import autocommit
    autocommit(util.MYSQL_URI,
               pyformat_sqldirs,
               MySQLdb.ProgrammingError,
               MySQLdb.OperationalError)


@pytest.mark.mysql
def test_autocommit_pool(pyformat_sqldirs):
    from .test_db import autocommit
    autocommit(util.MYSQL_POOL_URI,
               pyformat_sqldirs,
               MySQLdb.ProgrammingError,
               MySQLdb.OperationalError)


@pytest.mark.mysql
def test_rollback(mydb, mypooldb):
    from .test_db import rollback
    for db in (mydb, mypooldb):
        rollback(db)


@pytest.mark.mysql
def test_multiple_records(mydb, mypooldb):
    from .test_db import multiple_records
    multiple_records(mydb, lambda user: user['name'])
    multiple_records(mypooldb, lambda user: user[0])


@pytest.mark.mysql
def test_multiple_records_error(mydb, mypooldb):
    from .test_db import multiple_records_error
    for db in (mydb, mypooldb):
        multiple_records_error(db)


@pytest.mark.mysql
def test_tuple_cursor(mydbpersist, mypooldb):
    for db in (mydbpersist, mypooldb):
        with db.cursor as cursor:
            user = db.user.by_name(cursor, name='User 4').one()
            assert user[0] == 'user.4@example.com'
            with pytest.raises(TypeError):
                user['email']
            cursor.rollback()


@pytest.mark.mysql
def test_dict_cursor(mydb, mypooldbdict):
    for db in (mydb, mypooldbdict):
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
def test_execute(mydb, mypooldbdict):
    from .test_db import execute
    for db in (mydb, mypooldbdict):
        execute(db, MySQLdb.ProgrammingError)
