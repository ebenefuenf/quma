from unittest.mock import Mock

import pytest

from . import util
from ..exc import FetchError
from ..provider.postgresql import Connection

try:
    import psycopg2
except ImportError:
    psycopg2 = None


def setup_function(function):
    util.setup_pg_db()


@pytest.mark.postgres
def test_conn_attr(pgdb, pgpooldb):
    from .test_db import conn_attr
    for db in (pgdb, pgpooldb):
        conn_attr(db, 'autocommit', False, True)


@pytest.mark.postgres
def test_cursor(pgdb, pgpooldb):
    from .test_db import cursor
    for db in (pgdb, pgpooldb):
        cursor(db)


@pytest.mark.postgres
def test_cursor_call(pgdb, pgpooldb):
    from .test_db import cursor_call
    for db in (pgdb, pgpooldb):
        cursor_call(db)


@pytest.mark.postgres
def test_count(pgdb, pgpooldb):
    from .test_db import (
        count,
        rowcount,
    )
    for db in (pgdb, pgpooldb):
        count(db)
        rowcount(db)


@pytest.mark.postgres
def test_exists(pgdb, pgpooldb):
    from .test_db import exists
    for db in (pgdb, pgpooldb):
        exists(db)


@pytest.mark.postgres
def test_query_cache(pgdb, pgpooldb):
    from .test_db import query_cache
    for db in (pgdb, pgpooldb):
        query_cache(db)


@pytest.mark.postgres
def test_first(pgdb, pgpooldb):
    from .test_db import first
    for db in (pgdb, pgpooldb):
        first(db)


@pytest.mark.postgres
def test_value(pgdb, pgpooldb):
    from .test_db import value
    for db in (pgdb, pgpooldb):
        value(db)


@pytest.mark.postgres
def test_value_str(pgdb, pgpooldb):
    from .test_db import value_str
    for db in (pgdb, pgpooldb):
        value_str(db)


@pytest.mark.postgres
def test_query_attr(pgdb, pgpooldb):
    from .test_db import query_attr
    for db in (pgdb, pgpooldb):
        query_attr(db)


@pytest.mark.postgres
def test_getitem(pgdb, pgpooldb):
    from .test_db import getitem
    for db in (pgdb, pgpooldb):
        getitem(db)


@pytest.mark.postgres
def test_bool(pgdb, pgpooldb):
    from .test_db import tbool
    for db in (pgdb, pgpooldb):
        tbool(db)


@pytest.mark.postgres
def test_commit(pgdb, pgpooldb):
    from .test_db import commit
    for db in (pgdb, pgpooldb):
        commit(db)


@pytest.mark.postgres
def test_autocommit(pyformat_sqldirs):
    from .test_db import autocommit
    autocommit(util.PGSQL_URI,
               pyformat_sqldirs,
               psycopg2.ProgrammingError,
               psycopg2.ProgrammingError)


@pytest.mark.postgres
def test_autocommit_pool(pyformat_sqldirs):
    from .test_db import autocommit
    autocommit(util.PGSQL_POOL_URI,
               pyformat_sqldirs,
               psycopg2.ProgrammingError,
               psycopg2.ProgrammingError)


@pytest.mark.postgres
def test_rollback(pgdb, pgpooldb):
    from .test_db import rollback
    for db in (pgdb, pgpooldb):
        rollback(db)


@pytest.mark.postgres
def test_changeling_cursor(pgdb, pgpooldb):
    from .test_db import changeling_cursor
    for db in (pgdb, pgpooldb):
        changeling_cursor(db)


@pytest.mark.postgres
def test_changeling_cursor_hidden_members(pgdb):
    with pgdb.cursor as cursor:
        user = pgdb.user.by_name(cursor, name='User 1').one()
        assert user.count == 13
        assert user._count(13) == 2


@pytest.mark.postgres
def test_no_changeling_cursor(pgdb_persist):
    from .test_db import no_changeling_cursor
    no_changeling_cursor(pgdb_persist,
                         lambda user: user.email,
                         AttributeError)


@pytest.mark.postgres
def test_multiple_records(pgdb, pgpooldb):
    from .test_db import multiple_records
    for db in (pgdb, pgpooldb):
        multiple_records(db, lambda user: user.name)


@pytest.mark.postgres
def test_multiple_records_error(pgdb, pgpooldb):
    from .test_db import multiple_records_error
    for db in (pgdb, pgpooldb):
        multiple_records_error(db)


@pytest.mark.postgres
def test_faulty_fetch(dburl):
    cursor = type('C', (), {})
    cn = Connection(dburl)

    def fetch():
        raise psycopg2.ProgrammingError('test error')

    cursor.fetchall = fetch
    cursor.fetchmany = fetch
    with pytest.raises(FetchError) as e:
        cn.get_cursor_attr(cursor, 'fetchall')()
    assert str(e.value.error) == 'test error'
    with pytest.raises(FetchError) as e:
        cn.get_cursor_attr(cursor, 'fetchmany')()


@pytest.mark.postgres
def test_get_cursor_attr(pgdb):
    conn = pgdb.conn
    cursor = Mock()
    cursor.fetchall = Mock()
    cursor.fetchall.__name__ = 'fetchall'
    cursor.fetchall.side_effect = psycopg2.ProgrammingError(
        'no results to fetch')
    assert conn.get_cursor_attr(cursor, 'fetchall')() == ()
    cursor.fetchall.side_effect = psycopg2.ProgrammingError('test')
    with pytest.raises(FetchError) as e:
        conn.get_cursor_attr(cursor, 'fetchall')()
    assert str(e.value.error) == 'test'

    # Test Script._fetch except
    with pgdb.cursor as cursor:
        cursor.raw_cursor.fetchall = Mock()
        cursor.raw_cursor.fetchall.__name__ = 'fetchall'
        cursor.raw_cursor.fetchall.side_effect = FetchError(
                psycopg2.ProgrammingError('pg-exc-test'))
        with pytest.raises(psycopg2.ProgrammingError) as e:
            pgdb.users.all(cursor).first()
        assert str(e.value) == 'pg-exc-test'


@pytest.mark.postgres
def test_many(pgdb, pgpooldb):
    from .test_db import many
    for db in (pgdb, pgpooldb):
        many(db)


@pytest.mark.postgres
def test_many_default(pgdb, pgpooldb):
    from .test_db import many_default
    for db in (pgdb, pgpooldb):
        many_default(db)


@pytest.mark.postgres
def test_unbunch(pgdb, pgpooldb):
    from .test_db import unbunch
    for db in (pgdb, pgpooldb):
        unbunch(db)


@pytest.mark.postgres
def test_execute(pgdb, pgpooldb):
    from .test_db import execute
    for db in (pgdb, pgpooldb):
        execute(db, psycopg2.ProgrammingError)
