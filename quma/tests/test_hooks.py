import logging

import pytest

from .. import (
    APIError,
    Database,
    Execution,
    PlaceholderError,
)
from ..script import Script
from . import util
from .test_transaction import (
    DRIVERS,
    prepare,
)

SERVERS = DRIVERS[1:]
# The keyword each driver's execute() has for the parameters.
PARAMS_KEYWORD = {
    "psycopg2": "vars",
    "psycopg": "params",
    "mysqlclient": "args",
}


@pytest.fixture(params=DRIVERS)
def driver(request):
    return request.param


@pytest.fixture
def open_db(driver, named_sqldirs):
    uri = prepare(driver)
    dbs = []

    def create(**kwargs):
        dbs.append(Database(uri, named_sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        db.close()


@pytest.fixture
def events():
    return []


@pytest.fixture
def db(open_db, events):
    return open_db(on_execute=events.append)


def sleep(driver, seconds):
    if driver.startswith("psycopg"):
        return f"SELECT pg_sleep({seconds})"
    return f"SELECT SLEEP({seconds})"


def qmark(driver):
    return "?" if driver == "sqlite3" else "%s"


def sql_dirs(root, files):
    for name, content in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
    return root


def test_script_reports_what_the_driver_received(db, driver, events):
    with db.cursor as cur:
        rows = cur.users.by_name(name="User 1").all()
    assert len(rows) == 1
    [event] = events
    assert isinstance(event, Execution)
    assert event.name == "users/by_name"
    placeholder = ":name" if driver == "sqlite3" else "%(name)s"
    assert f"name = {placeholder}" in event.sql
    assert event.params == {"name": "User 1"}
    assert event.duration > 0
    assert event.error is None


def test_rowcount(db, driver, events):
    with db.cursor as cur:
        cur.users.by_name(name="User 1").all()
        cur.users.remove(name="User 1").run()
        cur.users.remove(name="Nobody").run()
        cur.rollback()
    selected = None if driver == "sqlite3" else 1
    assert [event.rowcount for event in events] == [selected, 1, 0]


def test_statements_outside_scripts_have_no_name(db, events):
    with db.cursor as cur:
        cur.query("SELECT 1").all()
        cur.execute("SELECT 2")
        cur.fetchall()
        cur.commit()
    db.execute("SELECT 3")
    assert [event.name for event in events] == [None, None, None]
    assert [event.sql for event in events] == [
        "SELECT 1",
        "SELECT 2",
        "SELECT 3",
    ]


def test_executemany(db, driver, events):
    sql = f"UPDATE users SET city = 'X' WHERE id = {qmark(driver)}"
    params = [(1,), (2,)]
    with db.cursor as cur:
        cur.executemany(sql, params)
        cur.rollback()
    [event] = events
    assert event.sql == sql
    assert event.params == params
    assert event.rowcount == 2


@pytest.mark.parametrize("driver", SERVERS)
def test_params_given_by_keyword(db, driver, events):
    keyword = PARAMS_KEYWORD[driver.removesuffix("+pool")]
    with db.cursor as cur:
        cur.execute("SELECT %s", **{keyword: [1]})
        cur.fetchall()
    [event] = events
    assert event.sql == "SELECT %s"
    assert event.params == [1]


@pytest.mark.parametrize("driver", SERVERS)
def test_sql_given_by_keyword(db, events):
    with db.cursor as cur:
        cur.execute(query="SELECT 1")
        cur.fetchall()
    assert [event.sql for event in events] == ["SELECT 1"]


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2"])
def test_callproc(db, events):
    with db.cursor as cur:
        cur.callproc("upper", ["x"])
        assert cur.fetchall()[0][0] == "X"
    [event] = events
    assert event.sql == "upper"
    assert event.params == ["x"]


def test_failed_statement(db, events):
    with db.cursor as cur:
        with pytest.raises(Exception, match="missing") as raised:
            cur.query("SELECT * FROM missing").all()
        cur.rollback()
    [event] = events
    assert event.sql == "SELECT * FROM missing"
    assert event.error is raised.value
    assert event.rowcount is None
    assert event.duration >= 0


@pytest.mark.parametrize("driver", SERVERS)
def test_duration_covers_the_statement(db, driver, events):
    with db.cursor as cur:
        cur.query(sleep(driver, 0.05)).all()
    assert events[0].duration >= 0.04


def test_failing_hook_keeps_the_result(open_db, caplog):
    def hook(event):
        raise ValueError("bug in the hook")

    db = open_db(on_execute=hook)
    with db.cursor as cur:
        assert len(cur.users.by_name(name="User 1").all()) == 1
        cur.users.remove(name="User 1").run()
        cur.commit()
    with db.cursor as cur:
        assert len(cur.users.by_name(name="User 1").all()) == 0
    assert "users/by_name" in caplog.text
    assert "bug in the hook" in caplog.text


def test_failing_hook_keeps_the_statements_error(open_db):
    def hook(event):
        raise ValueError("bug in the hook")

    db = open_db(on_execute=hook)
    with db.cursor as cur:
        with pytest.raises(Exception, match="missing"):
            cur.query("SELECT * FROM missing").all()
        cur.rollback()


def test_statement_that_never_ran_isnt_reported(db, events):
    with db.cursor as cur:
        with pytest.raises(PlaceholderError):
            cur.query("SELECT %(native)s", native=1).all()
    assert events == []


def test_transaction_control_isnt_reported(db, events):
    with db.cursor as cur:
        with cur.transaction():
            cur.users.remove(name="User 1").run()
            with cur.transaction():
                cur.users.remove(name="User 2").run()
    assert [event.name for event in events] == ["users/remove"] * 2


def test_connection_check_isnt_reported(open_db, events):
    db = open_db(pessimistic=True, on_execute=events.append)
    for _ in range(2):
        with db.cursor as cur:
            cur.query("SELECT 1").all()
    assert [event.sql for event in events] == ["SELECT 1"] * 2


def test_stream_reports_its_opening_only(db, driver, events):
    with db.cursor as cur:
        rows = list(cur.users.all().stream(2))
    assert len(rows) == 7
    [event] = events
    assert event.name == "users/all"
    assert event.rowcount is None
    assert event.error is None
    assert event.sql.startswith("DECLARE") == driver.startswith("psycopg")


def test_stream_closed_early_reports_its_opening_only(db, events):
    with db.cursor as cur:
        for _row in cur.users.all().stream(2):
            break
    assert [event.name for event in events] == ["users/all"]


def test_stream_that_fails_to_open(db, events):
    with db.cursor as cur:
        with pytest.raises(Exception, match="missing") as raised:
            list(cur.query("SELECT * FROM missing").stream())
        cur.rollback()
    [event] = events
    assert event.error is raised.value


def test_script_on_a_cursor_that_was_never_opened(db, events):
    with pytest.raises(APIError, match="no open connection"):
        db.cursor.users.all().all()
    assert events == []


def test_echo_works_next_to_the_hook(events, named_sqldirs, capsys):
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI, on_execute=events.append, echo=True)
    with db.cursor as cur:
        cur.query("SELECT 1").all()
    db.close()
    assert "SELECT 1" in capsys.readouterr().out
    assert len(events) == 1


@pytest.mark.parametrize("cache", [False, True])
def test_script_names(tmp_path, events, cache):
    sqldir = sql_dirs(
        tmp_path,
        {
            "at_root.sql": "SELECT 1",
            "users/plain.sql": "SELECT 2",
            "users/rendered.msql": "SELECT ${1 + 2}",
        },
    )
    db = Database(
        util.SQLITE_MEMORY, sqldir, cache=cache, on_execute=events.append
    )
    with db.cursor as cur:
        cur.at_root().all()
        cur.users.plain().all()
        cur.users.rendered().all()
        db.users.plain(cur).all()
    db.close()
    assert [event.name for event in events] == [
        "at_root",
        "users/plain",
        "users/rendered",
        "users/plain",
    ]
    assert events[2].sql.strip() == "SELECT 3"


def test_script_names_with_several_directories(tmp_path, events):
    first = sql_dirs(tmp_path / "first", {"a.sql": "SELECT 1"})
    second = sql_dirs(
        tmp_path / "second", {"b.sql": "SELECT 2", "ns/c.sql": "SELECT 3"}
    )
    db = Database(
        util.SQLITE_MEMORY, [str(first), second], on_execute=events.append
    )
    with db.cursor as cur:
        cur.a().all()
        cur.b().all()
        cur.ns.c().all()
    db.close()
    assert [event.name for event in events] == ["a", "b", "ns/c"]


def test_script_name_of_a_file_named_like_a_namespace_member(tmp_path, events):
    sqldir = sql_dirs(tmp_path, {"users/echo.sql": "SELECT 1"})
    db = Database(
        util.SQLITE_MEMORY, sqldir, cache=True, on_execute=events.append
    )
    with db.cursor as cur:
        cur.users._echo().all()
    db.close()
    assert [event.name for event in events] == ["users/echo"]


def test_script_name_through_an_alias(named_sqldirs, events):
    db = Database(util.SQLITE_MEMORY, named_sqldirs, on_execute=events.append)
    with db.cursor as cur:
        cur.execute(util.CREATE_USERS)
        cur.user.all().all()
    db.close()
    assert events[-1].name == "users/all"


def test_script_factory_with_the_known_signature(tmp_path, events):
    def factory(content, echo, is_template, sqldirs, prepare_params=None):
        return Script(content, echo, is_template, sqldirs, prepare_params)

    sqldir = sql_dirs(tmp_path, {"users/plain.sql": "SELECT 1"})
    db = Database(
        util.SQLITE_MEMORY,
        sqldir,
        script_factory=factory,
        on_execute=events.append,
    )
    with db.cursor as cur:
        cur.users.plain().all()
    db.close()
    assert [event.name for event in events] == ["users/plain"]


def test_coroutine_function_is_rejected():
    async def hook(event):
        pass

    with pytest.raises(TypeError, match="plain function"):
        Database(util.SQLITE_MEMORY, on_execute=hook)  # ty: ignore[invalid-argument-type]


def test_debug_log(open_db, caplog):
    db = open_db()
    with caplog.at_level(logging.DEBUG, logger="quma"):
        with db.cursor as cur:
            cur.users.by_name(name="User 1").all()
    [record] = caplog.records
    assert record.name == "quma"
    assert record.levelno == logging.DEBUG
    message = record.getMessage()
    assert message.startswith("users/by_name: ")
    assert " ms, rowcount " in message
    assert "FROM\n    users" in message
    assert "User 1" not in message


def test_debug_log_of_a_query_without_a_name(open_db, caplog):
    db = open_db()
    with caplog.at_level(logging.DEBUG, logger="quma"):
        with db.cursor as cur:
            cur.query("SELECT 1").all()
    [record] = caplog.records
    assert record.getMessage().startswith("query: ")
    assert record.getMessage().endswith("\nSELECT 1")


def test_debug_log_of_a_failure_leaves_out_the_drivers_message(
    open_db, caplog
):
    db = open_db()
    with caplog.at_level(logging.DEBUG, logger="quma"):
        with db.cursor as cur:
            with pytest.raises(Exception, match=r"(?i)unique|duplicate") as e:
                cur.users.add(
                    id=1, name="Secret", email="secret@x", city="Y"
                ).run()
            cur.rollback()
    [record] = caplog.records
    message = record.getMessage()
    assert f"failed with {type(e.value).__name__}" in message
    assert str(e.value) not in message
    assert "Secret" not in message


def test_no_log_above_debug(open_db, caplog):
    db = open_db()
    with caplog.at_level(logging.INFO, logger="quma"):
        with db.cursor as cur:
            cur.users.by_name(name="User 1").all()
    assert caplog.records == []


def test_debug_log_and_hook_both_report(db, events, caplog):
    with caplog.at_level(logging.DEBUG, logger="quma"):
        with db.cursor as cur:
            cur.users.by_name(name="User 1").all()
    assert len(caplog.records) == 1
    assert len(events) == 1
