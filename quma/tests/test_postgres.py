import pickle
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .. import Database
from ..exc import FetchError
from . import util


def setup_function(function):
    util.setup_pg_db()


@pytest.mark.postgres
def test_conn_attr(pgdb, pgpooldb):
    from .test_db import conn_attr

    for db in (pgdb, pgpooldb):
        conn_attr(db, "autocommit", False, True)


@pytest.mark.postgres
def test_cursor(pgdb, pgpooldb):
    from .test_db import the_cursor

    for db in (pgdb, pgpooldb):
        the_cursor(db)


@pytest.mark.postgres
def test_carrier(pgdb):
    from .test_db import carrier

    carrier(pgdb)


@pytest.mark.postgres
def test_pool_carrier(pgpooldb):
    from .test_db import pool_carrier

    pool_carrier(pgpooldb)


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
def test_get_item(pgdb, pgpooldb):
    from .test_db import get_item

    for db in (pgdb, pgpooldb):
        get_item(db)


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
def test_autocommit(pgdriver, pyformat_sqldirs):
    from .test_db import autocommit

    autocommit(
        pgdriver.uri,
        pyformat_sqldirs,
        pgdriver.dbapi.ProgrammingError,
        pgdriver.dbapi.ProgrammingError,
    )


@pytest.mark.postgres
def test_autocommit_pool(pgdriver, pyformat_sqldirs):
    from .test_db import autocommit

    autocommit(
        pgdriver.pool_uri,
        pyformat_sqldirs,
        pgdriver.dbapi.ProgrammingError,
        pgdriver.dbapi.ProgrammingError,
    )


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
        user = pgdb.user.by_name(cursor, name="User 1").one()
        assert user.count == 13
        assert user._count(13) == 2


@pytest.mark.postgres
def test_no_changeling_cursor(pgdb_persist):
    from .test_db import no_changeling_cursor

    no_changeling_cursor(pgdb_persist, lambda user: user.email, AttributeError)


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
def test_faulty_fetch(pgdburl):
    psycopg2 = pytest.importorskip("psycopg2")
    from ..provider.psycopg2 import Connection

    cn = Connection(pgdburl)

    def fetch():
        raise psycopg2.ProgrammingError("test error")

    cursor = SimpleNamespace(fetchall=fetch, fetchmany=fetch)
    with pytest.raises(FetchError) as e:
        cn.get_cursor_attr(cursor, "fetchall")()
    assert str(e.value.error) == "test error"
    with pytest.raises(FetchError) as e:
        cn.get_cursor_attr(cursor, "fetchmany")()


@pytest.mark.postgres
def test_get_cursor_attr(pyformat_sqldirs, monkeypatch):
    psycopg2 = pytest.importorskip("psycopg2")
    pgdb = Database(util.PGSQL_URI, pyformat_sqldirs, changeling=True)
    conn = pgdb.conn
    assert conn is not None
    cursor = Mock()
    cursor.fetchall = Mock()
    cursor.fetchall.__name__ = "fetchall"
    cursor.fetchall.side_effect = psycopg2.ProgrammingError(
        "no results to fetch"
    )
    assert conn.get_cursor_attr(cursor, "fetchall")() == ()
    cursor.fetchall.side_effect = psycopg2.ProgrammingError("test")
    with pytest.raises(FetchError) as e:
        conn.get_cursor_attr(cursor, "fetchall")()
    assert str(e.value.error) == "test"

    # Test Script._fetch except
    with pgdb.cursor as cursor:
        raw_cursor = cursor.raw_cursor
        assert raw_cursor is not None
        fetchall = Mock(
            side_effect=FetchError(psycopg2.ProgrammingError("pg-exc-test"))
        )
        fetchall.__name__ = "fetchall"
        monkeypatch.setattr(raw_cursor, "fetchall", fetchall, raising=False)
        with pytest.raises(psycopg2.ProgrammingError) as e:
            pgdb.users.all(cursor).first()
        assert str(e.value) == "pg-exc-test"


@pytest.mark.postgres
def test_psycopg_get_cursor_attr(pyformat_sqldirs):
    psycopg = pytest.importorskip("psycopg")
    db = Database(util.pg_uri("psycopg"), pyformat_sqldirs)
    conn = db.conn
    assert conn is not None
    cursor = Mock()
    cursor.description = None
    cursor.fetchall.side_effect = psycopg.ProgrammingError("no result")
    assert conn.get_cursor_attr(cursor, "fetchall")() == ()
    cursor.description = [Mock()]
    cursor.fetchall.side_effect = psycopg.ProgrammingError("test")
    with pytest.raises(FetchError) as e:
        conn.get_cursor_attr(cursor, "fetchall")()
    assert str(e.value.error) == "test"


@pytest.mark.postgres
def test_fetch_without_result(pgdb, pgpooldb):
    for db in (pgdb, pgpooldb):
        with db.cursor as cursor:
            cursor.execute("CREATE TEMP TABLE test (id int);")
            assert cursor.fetchall() == ()
            assert cursor.fetchmany() == ()


@pytest.mark.postgres
def test_multiple_statements(pgdb, pgpooldb):
    sql = (
        "CREATE TEMP TABLE test (id int);"
        "INSERT INTO test VALUES (1), (2), (3);"
        "UPDATE test SET id = id * 10 WHERE id > 1;"
        "SELECT id FROM test ORDER BY id;"
    )
    for db in (pgdb, pgpooldb):
        with db.cursor as cursor:
            cursor.execute(sql)
            assert cursor.rowcount == 3
            assert [row[0] for row in cursor.fetchall()] == [1, 20, 30]


@pytest.mark.postgres
def test_row_mapping(pgdb_persist):
    with pgdb_persist.cursor as cursor:
        user = pgdb_persist.user.by_name(cursor, name="User 3").one()
        assert list(user.keys()) == ["email", "city", "count", "count2"]
        assert list(user.values()) == list(user)
        assert dict(user) == dict(user.items()) == user.copy()
        assert user.get("city") == "City B"
        assert user.get("missing", "default") == "default"
        assert "email" in user
        user["email"] = "test@example.com"
        assert user[0] == "test@example.com"
        user[1] = "Test City"
        assert user["city"] == "Test City"
        restored = pickle.loads(pickle.dumps(user))
        assert restored == user
        assert restored["email"] == "test@example.com"
        cursor.rollback()


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
def test_mapping(pgdb, pgdb_persist, pgpooldb):
    from .test_mapping import map_all

    for db in (pgdb, pgdb_persist, pgpooldb):
        map_all(db)


@pytest.mark.postgres
def test_execute(pgdriver, pgdb, pgpooldb):
    from .test_db import execute

    for db in (pgdb, pgpooldb):
        execute(db, pgdriver.dbapi.ProgrammingError)


@pytest.mark.postgres
def test_execute_returns_connection(pgdriver, pgpooldb):
    from .test_db import execute_returns_connection

    execute_returns_connection(pgpooldb, pgdriver.dbapi.ProgrammingError)


@pytest.mark.postgres
def test_call_and_enter(pgpooldb):
    from .test_db import call_and_enter

    call_and_enter(pgpooldb, lambda conn: conn.autocommit)


@pytest.mark.postgres
def test_close_twice(pgpooldb):
    from .test_db import close_twice

    close_twice(pgpooldb)


@pytest.mark.postgres
def test_cursor_query(pgdb, pgpooldb):
    sql = "SELECT name, city FROM users WHERE email = %s AND 1 = %s;"
    for db in (pgdb, pgpooldb):
        with db.cursor as cur:
            q = cur.query(sql, "user.1@example.com", 1)
            assert q.value() == "User 1"


@pytest.mark.postgres
def test_prepared_statement(pgdb, pgpooldb):
    for db in (pgdb, pgpooldb):
        with db.cursor as cur:
            cur.users.pgsql_prepare().run()
            sql = "EXECUTE prep('user.{}@example.com', 1);"
            for i in range(1, 5):
                q = cur.query(sql.format(i))
                assert q.value() == f"User {i}"
            cur.query("DEALLOCATE PREPARE prep;").run()


@pytest.mark.postgres
def test_echo_parameter(pgdb_echo, pgpooldb_echo, capsys):
    for db in (pgdb_echo, pgpooldb_echo):
        with db.cursor as cursor:
            db.user.by_email(cursor, "user.1@example.com", 1).one()
            assert capsys.readouterr().out.endswith(
                "SELECT name, city FROM users WHERE email = "
                "'user.1@example.com' AND 1 = 1;\n"
            )
