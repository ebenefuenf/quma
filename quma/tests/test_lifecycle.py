"""What a cursor and its connection do in every state: opened twice, used after
closing, after the server dropped the connection. Each driver has its own way
to fail here, and a slot lost in a pool only shows on a later checkout."""

import sqlite3
import threading
import time
from typing import Any

import pytest

from .. import Database, exc
from . import util

SQL = "SELECT 1 AS a"
CONNECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "plain": ("", {}),
    "persist": ("", {"persist": True}),
    "pool": ("+pool", {"size": 1, "overflow": 1, "timeout": 0.2}),
}


@pytest.fixture(
    params=[
        "sqlite3",
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ]
)
def driver(request, tmp_path):
    name = request.param
    pytest.importorskip("MySQLdb" if name == "mysqlclient" else name)
    if name == "sqlite3":
        return f"sqlite3:///{tmp_path / 'lifecycle.sqlite'}"
    if name == "mysqlclient":
        return util.MYSQL_URI
    return util.pg_uri(name)


@pytest.fixture(params=CONNECTIONS)
def database(request, driver):
    suffix, options = CONNECTIONS[request.param]
    scheme, rest = driver.split("://", 1)
    db = Database(f"{scheme}{suffix}://{rest}", **options)
    yield db
    db.close()


def lose(raw):
    if isinstance(raw, sqlite3.Connection):
        raw.close()
        return
    if hasattr(raw, "thread_id"):
        uri, kill = util.MYSQL_URI, f"KILL {raw.thread_id()}"
    else:
        pid = raw.info.backend_pid
        uri = util.pg_uri("psycopg")
        kill = f"SELECT pg_terminate_backend({pid}, 5000)"
    killer = Database(uri)
    with killer.cursor as cur:
        cur.execute(kill)
    killer.close()
    # MySQL's KILL returns before the connection is gone.
    time.sleep(0.05)


def assert_no_slot_lost(db):
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1


def with_and_with(db):
    with db.cursor as cur:
        with cur:
            pass


def called_and_with(db):
    with db.cursor() as cur:
        with cur:
            pass


def called_twice(db):
    cur = db.cursor()
    try:
        cur()
    finally:
        cur.close()


def created_twice(db):
    cur = db.cursor
    cur.create_cursor()
    try:
        cur.create_cursor()
    finally:
        cur.close()


def with_and_created(db):
    with db.cursor as cur:
        cur.create_cursor()


def carried_with_and_with(db):
    carrier = object()
    try:
        with db(carrier).cursor as cur:
            with cur:
                pass
    finally:
        db.release(carrier)


@pytest.mark.parametrize(
    "open_twice",
    [
        with_and_with,
        called_and_with,
        called_twice,
        created_twice,
        with_and_created,
        carried_with_and_with,
    ],
)
def test_an_open_cursor_refuses_to_open(database, open_twice):
    with pytest.raises(exc.APIError, match="already open"):
        open_twice(database)
    assert_no_slot_lost(database)


def test_a_closed_cursor_opens_again(database):
    cur = database.cursor
    for _ in range(2):
        with cur:
            assert cur.query(SQL).value() == 1
    cur.create_cursor()
    cur.close()
    with cur:
        assert cur.query(SQL).value() == 1
    assert_no_slot_lost(database)


USES = {
    "query": lambda cur: cur.query(SQL).all(),
    "execute": lambda cur: cur.execute(SQL),
    "fetchall": lambda cur: cur.fetchall(),
    "fetchone": lambda cur: cur.fetchone(),
    "mogrify": lambda cur: cur.mogrify(SQL, {}),
    "commit": lambda cur: cur.commit(),
    "rollback": lambda cur: cur.rollback(),
    "block": lambda cur: cur.transaction().__enter__(),
}


@pytest.mark.parametrize("use", USES.values(), ids=USES.keys())
def test_a_cursor_without_a_connection_says_so(database, use):
    cur = database.cursor
    with pytest.raises(exc.APIError, match="no open connection"):
        use(cur)
    with cur:
        cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        use(cur)
    assert_no_slot_lost(database)


@pytest.mark.parametrize("use", ["query", "execute", "fetchall", "mogrify"])
def test_a_closed_carried_cursor_says_so(database, use):
    carrier = object()
    with database(carrier).cursor as cur:
        cur.execute(SQL)
    with pytest.raises(exc.APIError, match="no open connection"):
        USES[use](cur)
    database.release(carrier)
    assert_no_slot_lost(database)


def test_a_closed_carried_cursor_can_still_commit(database):
    carrier = object()
    with database(carrier).cursor as cur:
        cur.execute(SQL)
    cur.commit()
    database.release(carrier)
    assert_no_slot_lost(database)


def test_mogrify_binds_the_values(driver):
    placeholder = "?" if driver.startswith("sqlite3") else "%(v)s"
    db = Database(driver)
    with db.cursor as cur:
        cur.execute(SQL)
        bound = cur.mogrify(f"SELECT {placeholder}", {"v": 7})
    assert bound == ("SELECT ?" if placeholder == "?" else "SELECT 7")


def query(cur):
    return cur.query(SQL).all()


def execute(cur):
    return cur.execute(SQL)


def stream(cur):
    return next(iter(cur.query(SQL).stream()))


def block(cur):
    with cur.transaction():
        cur.query(SQL).all()


@pytest.mark.parametrize("use", [query, execute, stream, block])
def test_a_lost_connection_raises_connection_lost(database, use):
    with database.cursor as cur:
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
    assert_recovers(database)


def assert_recovers(db):
    """A connection found broken only on its next use costs one statement."""
    stats = db.pool_stats()
    if stats is not None:
        assert stats.in_use == 0
    try:
        with db.cursor as cur:
            cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1


@pytest.mark.parametrize(
    "use", [lambda cur: cur.commit(), lambda cur: cur.rollback()]
)
def test_ending_a_transaction_on_a_lost_connection(database, use):
    with database.cursor as cur:
        cur.execute(SQL)
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            use(cur)
    assert_recovers(database)


def test_a_block_after_a_failed_statement_on_a_lost_connection(database):
    with database.cursor as cur:
        lose(cur.raw_conn)
        with pytest.raises(exc.ConnectionLost):
            cur.query(SQL).all()
        with pytest.raises(exc.ConnectionLost):
            with cur.transaction():
                cur.query(SQL).all()
    assert_recovers(database)


def test_a_lost_connection_keeps_the_exception_of_the_block(database):
    with pytest.raises(ZeroDivisionError):
        with database.cursor as cur:
            lose(cur.raw_conn)
            raise ZeroDivisionError
    assert_recovers(database)


@pytest.fixture(params=["persist", "pool"])
def keeping(request, driver):
    suffix, options = CONNECTIONS[request.param]
    scheme, rest = driver.split("://", 1)
    db = Database(f"{scheme}{suffix}://{rest}", **options)
    yield db
    db.close()


def test_a_connection_lost_between_cursors(keeping):
    with keeping.cursor as cur:
        cur.execute(SQL)
        raw = cur.raw_conn
    lose(raw)
    assert_recovers(keeping)


def test_an_autocommit_cursor_after_a_lost_connection(keeping):
    with keeping.cursor as cur:
        cur.execute(SQL)
        raw = cur.raw_conn
    lose(raw)
    try:
        with keeping.cursor(autocommit=True) as cur:
            cur.query(SQL).all()
    except exc.ConnectionLost:
        pass
    assert_recovers(keeping)


def test_closing_a_database_with_a_lost_connection(database):
    with database.cursor as cur:
        raw = cur.raw_conn
        lose(raw)
        with pytest.raises(exc.ConnectionLost):
            cur.query(SQL).all()
    database.close()


def test_closing_a_database_while_a_cursor_is_open(database):
    cur = database.cursor
    cur.create_cursor()
    database.close()
    cur.close()


def test_a_closed_persistent_connection_stays_closed(driver):
    db = Database(driver, persist=True)
    cur = db.cursor
    db.close()
    with pytest.raises(exc.APIError, match="closed"):
        cur.create_cursor()


def test_pessimistic_finds_a_connection_closed_by_hand(driver):
    db = Database(driver, persist=True, pessimistic=True)
    with db.cursor as cur:
        raw: Any = cur.raw_conn
    raw.close()
    with db.cursor as cur:
        assert cur.query(SQL).value() == 1
    db.close()


COPY = "COPY (SELECT generate_series(1, 100000)) TO STDOUT"
MANY_ROWS = "SELECT generate_series(1, 100000) AS n"


@pytest.fixture(params=["plain", "persist", "pool"])
def psycopg_db(request):
    pytest.importorskip("psycopg")
    suffix, options = CONNECTIONS[request.param]
    db = Database(util.pg_uri(f"psycopg{suffix}"), **options)
    yield db
    db.close()


def within_seconds(call):
    """A deadlock on the driver's lock can't be interrupted, a thread can."""
    result = []

    def run():
        try:
            result.append(("ok", call()))
        except BaseException as e:
            result.append(("raised", e))

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(5)
    assert not thread.is_alive(), "It waits for the connection forever."
    kind, value = result[0]
    if kind == "raised":
        raise value
    return value


def kept_stream(cur):
    stream = cur.stream(MANY_ROWS)
    assert next(stream)[0] == 1
    return stream


@pytest.mark.postgres
@pytest.mark.parametrize(
    "use",
    [
        lambda cur: cur.query(SQL).all(),
        lambda cur: cur.execute(SQL),
        lambda cur: cur.commit(),
        lambda cur: cur.rollback(),
        lambda cur: cur.transaction().__enter__(),
        lambda cur: next(cur.stream(MANY_ROWS)),
        lambda cur: next(iter(cur.query(SQL).stream())),
    ],
)
def test_a_kept_driver_stream_refuses_other_statements(psycopg_db, use):
    def run():
        with psycopg_db.cursor as cur:
            stream = kept_stream(cur)
            with pytest.raises(exc.APIError, match="holds this connection"):
                use(cur)
            assert next(stream)[0] == 2

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "leave",
    [
        lambda db, cur: cur.__exit__(None, None, None),
        lambda db, cur: cur.close(),
        lambda db, cur: cur.put(),
    ],
)
def test_closing_a_cursor_ends_its_driver_stream(psycopg_db, leave):
    def run():
        cur = psycopg_db.cursor
        cur.__enter__()
        stream = kept_stream(cur)
        leave(psycopg_db, cur)
        with pytest.raises(exc.APIError, match="closed before its end"):
            next(stream)

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
def test_releasing_a_carrier_ends_a_driver_stream(psycopg_db):
    def run():
        carrier = object()
        cur = psycopg_db(carrier).cursor
        cur.create_cursor()
        kept_stream(cur)
        psycopg_db.release(carrier)

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
def test_closing_a_database_ends_a_driver_stream(psycopg_db):
    def run():
        cur = psycopg_db.cursor
        cur.create_cursor()
        stream = kept_stream(cur)
        psycopg_db.close()
        cur.close()
        with pytest.raises(exc.APIError, match="closed before its end"):
            next(stream)

    within_seconds(run)


@pytest.mark.postgres
def test_a_dropped_driver_stream_frees_the_connection(psycopg_db):
    def run():
        with psycopg_db.cursor as cur:
            for _ in cur.stream(MANY_ROWS):
                break
            # psycopg cancels the query, which aborts the transaction.
            cur.rollback()
            assert cur.query(SQL).value() == 1

    within_seconds(run)


@pytest.mark.postgres
def test_a_finished_driver_stream_frees_the_connection(psycopg_db):
    with psycopg_db.cursor as cur:
        assert [row[0] for row in cur.stream("SELECT 1 UNION SELECT 2")] == [
            1,
            2,
        ]
        assert cur.query(SQL).value() == 1
    assert_no_slot_lost(psycopg_db)


@pytest.mark.postgres
def test_a_driver_stream_raises_quma_errors(psycopg_db):
    with psycopg_db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            next(cur.stream("SELECT nope"))
        cur.rollback()
    assert_no_slot_lost(psycopg_db)


@pytest.mark.postgres
def test_a_quma_stream_waits_for_no_driver_stream(psycopg_db):
    def run():
        with psycopg_db.cursor as cur:
            rows = iter(cur.query(MANY_ROWS).stream(size=2))
            assert next(rows)[0] == 1
            stream = kept_stream(cur)
            assert next(rows)[0] == 2
            with pytest.raises(exc.APIError, match="holds this connection"):
                next(rows)
            stream.close()

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
@pytest.mark.parametrize(
    "use",
    [
        lambda cur: cur.query(SQL).all(),
        lambda cur: cur.commit(),
        lambda cur: cur.copy(COPY).__enter__(),
    ],
)
def test_a_copy_refuses_other_statements(psycopg_db, use):
    def run():
        with psycopg_db.cursor as cur:
            with cur.copy(COPY) as copy:
                assert copy.read()
                with pytest.raises(
                    exc.APIError, match="holds this connection"
                ):
                    use(cur)

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
def test_closing_a_cursor_inside_a_copy_ends_it(psycopg_db):
    def run():
        cur = psycopg_db.cursor
        cur.create_cursor()
        with cur.copy(COPY) as copy:
            assert copy.read()
            cur.close()

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
def test_a_copy_left_open_ends_with_its_cursor(psycopg_db):
    def run():
        with psycopg_db.cursor as cur:
            cur.copy(COPY).__enter__().read()

    within_seconds(run)
    within_seconds(lambda: assert_no_slot_lost(psycopg_db))


@pytest.mark.postgres
def test_a_copy_still_copies(psycopg_db):
    with psycopg_db.cursor as cur:
        cur.execute("CREATE TEMPORARY TABLE lifecycle_copy (a INT)")
        with cur.copy("COPY lifecycle_copy FROM STDIN") as copy:
            copy.write_row((7,))
        assert cur.query("SELECT a FROM lifecycle_copy").value() == 7
        cur.rollback()
    assert_no_slot_lost(psycopg_db)


def pyformat_or_qmark(driver, pyformat, qmark):
    return qmark if driver.startswith("sqlite3") else pyformat


MISTAKES = {
    "missing name": ("SELECT %(a)s AS a", ":a", {"b": 1}),
    "no names": ("SELECT %(a)s AS a", ":a", {}),
    "too few": ("SELECT %s AS a, %s AS b", "?, ?", (1,)),
    "too many": ("SELECT %s AS a", "?", (1, 2)),
    "list for a name": ("SELECT %(a)s AS a", ":a", (1,)),
    "name for a position": ("SELECT %s AS a", "?", {"a": 1}),
    "no sequence": ("SELECT %s AS a", "?", 5),
    "bad format": ("SELECT %d AS a", "?", ("x",)),
    "unknown format": ("SELECT %y AS a", "?", (1,)),
    "incomplete name": ("SELECT %(a) AS a", "?", {"a": 1}),
    "lone percent": ("SELECT 1 % AS a", "?", {"a": 1}),
}


@pytest.mark.filterwarnings("ignore:Binding 1:DeprecationWarning")
@pytest.mark.parametrize("mistake", MISTAKES.values(), ids=MISTAKES.keys())
def test_a_mistake_in_parameters_is_quma_error(database, driver, mistake):
    pyformat, qmark, params = mistake
    with database.cursor as cur:
        try:
            cur.execute(
                pyformat_or_qmark(driver, pyformat, f"SELECT {qmark}"), params
            )
        except exc.DatabaseError:
            pass
    assert_no_slot_lost(database)


@pytest.mark.parametrize("params", [{"b": 1}, {}], ids=["other", "none"])
def test_a_missing_name_raises_programming_error(driver, params):
    db = Database(driver)
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError, match="a"):
            cur.query("SELECT :a AS a", **params).all()
        with pytest.raises(exc.ProgrammingError, match="a"):
            next(iter(cur.query("SELECT :a AS a", **params).stream()))
    db.close()


def test_a_missing_name_is_a_key_error_too(driver):
    db = Database(driver)
    with db.cursor as cur:
        with pytest.raises(KeyError) as info:
            cur.query("SELECT :wanted AS a").all()
    assert isinstance(info.value, exc.MissingParameter)
    assert isinstance(info.value, exc.ProgrammingError)
    assert "wanted" in str(info.value)
    assert not str(info.value).startswith("'")
    db.close()


def test_a_missing_name_says_which(driver):
    if driver.startswith("sqlite3"):
        pytest.skip("Says it its own way, in a message of sqlite3.")
    db = Database(driver)
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError, match="missing: wanted"):
            cur.query("SELECT :wanted AS a").all()
    db.close()


def test_a_missing_name_in_a_script_names_it(driver, tmp_path):
    (tmp_path / "missing.sql").write_text("SELECT :a AS a")
    db = Database(driver, tmp_path)
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError) as info:
            cur.missing().all()
    assert info.value.script == "missing"
    db.close()


def test_positional_mistakes_in_native_mode(driver):
    db = Database(driver, placeholders="native")
    too_few = pyformat_or_qmark(
        driver, "SELECT %s AS a, %s AS b", "SELECT ?, ?"
    )
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            cur.query(too_few, 1).all()
    db.close()


def test_executemany_with_a_missing_name(driver):
    db = Database(driver)
    insert = pyformat_or_qmark(
        driver,
        "INSERT INTO lifecycle_many VALUES (%(a)s)",
        "INSERT INTO lifecycle_many VALUES (:a)",
    )
    with db.cursor as cur:
        cur.execute("CREATE TEMPORARY TABLE lifecycle_many (a INT)")
        with pytest.raises(exc.ProgrammingError):
            cur.executemany(insert, [{"a": 1}, {"b": 1}])
        cur.rollback()
    db.close()


def test_echo_keeps_the_error_of_a_statement(driver, capsys):
    db = Database(driver, echo=True)
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            cur.query("SELECT :a AS a").all()
    assert "SELECT" in capsys.readouterr().out
    db.close()


@pytest.mark.postgres
def test_threads_reopen_a_lost_persistent_connection_once():
    opened = []

    def on_connect(raw):
        opened.append(raw)
        time.sleep(0.05)

    db = Database(util.pg_uri("psycopg2"), persist=True, on_connect=on_connect)
    with db.cursor as cur:
        raw: Any = cur.raw_conn
        raw.close()
    conn = db.conn
    assert conn is not None
    start = threading.Barrier(8)
    got = []

    def checkout():
        start.wait()
        got.append(conn.get())

    threads = [threading.Thread(target=checkout) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(opened) == 2
    assert len({id(conn) for conn in got}) == 1
    db.close()
