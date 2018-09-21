from unittest.mock import Mock

import psycopg2
import pytest

from . import util
from ..exc import (
    FetchError,
    MultipleRecordsError,
)
from ..provider.postgresql import Connection


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
def test_commit(pgdb, pgpooldb):
    from .test_db import commit
    for db in (pgdb, pgpooldb):
        commit(db)


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
    cursor = Mock
    cursor.fetchall = Mock()
    cursor.fetchall.side_effect = psycopg2.ProgrammingError(
        'no results to fetch')
    assert conn.get_cursor_attr(cursor, 'fetchall')() == ()
    cursor.fetchall.side_effect = psycopg2.ProgrammingError('test')
    with pytest.raises(FetchError) as e:
        conn.get_cursor_attr(cursor, 'fetchall')()
    assert str(e.value.error) == 'test'

    # Test Query._fetch except
    with pgdb.cursor as cursor:
        cursor.raw_cursor.fetchall = Mock()
        cursor.raw_cursor.fetchall.side_effect = FetchError(
                psycopg2.ProgrammingError('pg-exc-test'))
        with pytest.raises(psycopg2.ProgrammingError) as e:
            pgdb.users.all(cursor)
        assert str(e.value) == 'pg-exc-test'


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
