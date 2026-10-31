import pytest

from .. import (
    Database,
    PlaceholderError,
)
from . import util

MySQLdb = pytest.importorskip("MySQLdb")


def setup_function(function):
    util.setup_mysql_db()


@pytest.mark.mysql
def test_conn_attr(mydb, mypooldb):
    from .test_db import conn_attr

    for db in (mydb, mypooldb):
        conn_attr(db, "encoding", "utf8", "latin1")


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
def test_autocommit(named_sqldirs):
    from .test_db import autocommit

    autocommit(
        util.MYSQL_URI,
        named_sqldirs,
        MySQLdb.ProgrammingError,
        MySQLdb.OperationalError,
    )


@pytest.mark.mysql
def test_autocommit_pool(named_sqldirs):
    from .test_db import autocommit

    autocommit(
        util.MYSQL_POOL_URI,
        named_sqldirs,
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

    multiple_records(mydb_dict, lambda user: user["name"])
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
            user = db.user.by_name(cursor, name="User 4").one()
            assert user[0] == "user.4@example.com"
            with pytest.raises(TypeError):
                user["email"]
            cursor.rollback()


@pytest.mark.mysql
def test_dict_cursor(mydb_dict, mypooldb_dict):
    for db in (mydb_dict, mypooldb_dict):
        with db.cursor as cursor:
            user = db.user.by_name(cursor, name="User 3").one()
            assert user["email"] == "user.3@example.com"
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
def test_mapping(mydb, mydb_dict, mypooldb):
    from .test_mapping import map_all

    for db in (mydb, mydb_dict, mypooldb):
        map_all(db)


@pytest.mark.mysql
def test_execute(mydb, mypooldb_dict):
    from .test_db import execute

    for db in (mydb, mypooldb_dict):
        execute(db, MySQLdb.ProgrammingError)


@pytest.mark.mysql
def test_execute_returns_connection(mypooldb):
    from .test_db import execute_returns_connection

    execute_returns_connection(mypooldb, MySQLdb.ProgrammingError)


@pytest.mark.mysql
def test_call_and_enter(mypooldb):
    from .test_db import call_and_enter

    call_and_enter(mypooldb, lambda conn: conn.get_autocommit())


@pytest.mark.mysql
def test_close_twice(mypooldb):
    from .test_db import close_twice

    close_twice(mypooldb)


@pytest.mark.mysql
def test_prepared_statement(mydb, mypooldb):
    for db in (mydb, mypooldb):
        with db.cursor as cur:
            cur.users.mysql_prepare().run()
            version = cur.query("SELECT VERSION();").value()
            if "MariaDB" not in version:  # pragma: no-cover
                # FIXME:
                print("Couldn't get the tests to run under MySQL 5")
                return
            sql = "EXECUTE prep USING 'user.{}@example.com', 1;"
            for i in range(1, 5):
                q = cur.query(sql.format(i))
                assert q.value() == f"User {i}"
            cur.query("DEALLOCATE PREPARE prep;").run()


@pytest.mark.mysql
def test_cursor_query(mydb, mypooldb):
    sql = "SELECT name, city FROM users WHERE email = :email AND 1 = :one;"
    for db in (mydb, mypooldb):
        with db.cursor as cur:
            q = cur.query(sql, email="user.1@example.com", one=1)
            assert q.value() == "User 1"


@pytest.mark.mysql
def test_failing_later_statement_returns_connection():
    db = Database(util.MYSQL_POOL_URI, size=1, overflow=0, timeout=0.1)
    with pytest.raises(MySQLdb.ProgrammingError):
        with db.cursor as cur:
            cur.execute("SELECT 1; SELECT * FROM missing_table")
            assert cur.fetchone()[0] == 1
    with db.cursor as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    db.close()


@pytest.mark.mysql
def test_echo_parameter(mydb_echo, mypooldb_echo, capsys):
    for db in (mydb_echo, mypooldb_echo):
        with db.cursor as cursor:
            db.user.by_name(cursor, name="User 1").one()
            assert capsys.readouterr().out.endswith(
                "WHERE\n    name = 'User 1';\n"
            )


@pytest.mark.mysql
def test_native_placeholders(mydb_native):
    with mydb_native.cursor as cur:
        user = cur.user.by_email("user.1@example.com", 1).one()
        assert user[0] == "User 1"
        assert cur.user.by_name(name="User 2").one()[1] == "City A"
        q = cur.query("SELECT CONCAT('User%%', %(n)s)", n=1)
        assert q.value() == "User%1"


@pytest.mark.mysql
def test_literal_percent(mydb, mypooldb):
    sql = "SELECT name FROM users WHERE name LIKE 'User%' AND city = :city"
    for db in (mydb, mypooldb):
        with db.cursor as cur:
            q = cur.query("SELECT count(*) FROM users WHERE name LIKE 'U%'")
            assert q.value() == 7
            assert cur.query(sql, city="City B").count() == 2
            assert cur.query("SELECT 7 % 4").value() == 3


@pytest.mark.mysql
def test_backslash_strings(mydb):
    with mydb.cursor as cur:
        sql = r"""SELECT '\\:a', "\\", :c"""
        assert tuple(cur.query(sql, c="x").one()) == ("\\:a", "\\", "x")
        with pytest.raises(PlaceholderError, match="NO_BACKSLASH_ESCAPES"):
            cur.query(r"SELECT 'it\'s :a', :c", c="x").one()


@pytest.mark.mysql
def test_execute_stays_native(mydb):
    with mydb.cursor as cur:
        cur.execute("SELECT CONCAT(%(x)s, '%%')", {"x": "a"})
        assert cur.fetchone()[0] == "a%"
    assert mydb.execute("SELECT '100%'")[0][0] == "100%"


@pytest.mark.mysql
def test_executable_comments(mydb):
    value = ", (SELECT 12345) AS c, "
    with mydb.cursor as cur:
        assert cur.query("SELECT /*! :x + */ 1", x=42).value() == 43
        row = cur.query("SELECT /*! '*/' AS a, */ ':y' AS b", y=value).one()
        assert tuple(row) == ("*/", ":y")
        for sql in (
            "SELECT /*!50000 :x + */ 1",
            "SELECT /*!99999 /* */ :x */ 1",
        ):
            with pytest.raises(PlaceholderError, match="versioned comment"):
                cur.query(sql, x=value).value()


@pytest.mark.mysql
def test_placeholders_and_quoting_settings(mydb):
    value = ", (SELECT 12345), "
    modes = ("", "NO_BACKSLASH_ESCAPES", "ANSI_QUOTES")
    with mydb.cursor as cur:
        for mode in modes:
            cur.execute(f"SET SESSION sql_mode = '{mode}'")
            with pytest.raises(PlaceholderError):
                cur.query("SELECT 'a\\', ':x'", x=value).one()
            row = cur.query("SELECT 'it''s :x', :x", x=value).one()
            assert tuple(row) == ("it's :x", value)
