import pickle
import sqlite3
import threading
import time
from types import SimpleNamespace

import pytest

from .. import (
    Database,
    exc,
)
from ..errors import (
    translate,
    translating,
)
from . import util
from .test_transaction import (
    DRIVERS,
    prepare,
)

SERVERS = DRIVERS[1:]
BASE = [
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("psycopg", marks=pytest.mark.postgres),
    pytest.param("mysqlclient", marks=pytest.mark.mysql),
]
POSTGRES = [
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("psycopg2+pool", marks=pytest.mark.postgres),
    pytest.param("psycopg", marks=pytest.mark.postgres),
    pytest.param("psycopg+pool", marks=pytest.mark.postgres),
]
MYSQL = [
    pytest.param("mysqlclient", marks=pytest.mark.mysql),
    pytest.param("mysqlclient+pool", marks=pytest.mark.mysql),
]
DEFERRED = [pytest.param("sqlite3", id="sqlite3"), *POSTGRES]

TABLES = (
    "DROP TABLE IF EXISTS err_child",
    "DROP TABLE IF EXISTS err_parent",
    """CREATE TABLE err_parent (
        id INT PRIMARY KEY,
        name VARCHAR(40) NOT NULL,
        short VARCHAR(2),
        age INT,
        CONSTRAINT uq_err_name UNIQUE (name),
        CONSTRAINT ck_err_age CHECK (age > 0))""",
    """CREATE TABLE err_child (
        id INT PRIMARY KEY,
        parent INT,
        CONSTRAINT fk_err_parent FOREIGN KEY (parent)
            REFERENCES err_parent (id))""",
    "INSERT INTO err_parent (id, name, age) VALUES (1, 'a', 1), (2, 'b', 2)",
    "INSERT INTO err_child (id, parent) VALUES (1, 1)",
)
UNIQUE_CODES = {
    "psycopg": "23505",
    "mysqlclient": 1062,
    "sqlite3": "SQLITE_CONSTRAINT_UNIQUE",
}


@pytest.fixture(params=DRIVERS)
def driver(request):
    return request.param


@pytest.fixture
def uri(driver):
    return prepare(driver)


@pytest.fixture
def open_db(uri, named_sqldirs):
    dbs = []

    def create(**kwargs):
        kwargs.setdefault("sqldirs", named_sqldirs)
        dbs.append(Database(uri, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        db.close()


@pytest.fixture
def db(open_db, driver):
    db = open_db()
    with db.cursor as cur:
        for statement in TABLES:
            cur.execute(statement)
        cur.commit()
    yield db
    with db.cursor as cur:
        cur.execute("DROP TABLE err_child")
        cur.execute("DROP TABLE err_parent")
        cur.commit()


def foreign_keys(cur, driver):
    if driver == "sqlite3":
        cur.execute("PRAGMA foreign_keys = ON")


def failure(db, driver, sql):
    with db.cursor as cur:
        foreign_keys(cur, driver)
        with pytest.raises(exc.DatabaseError) as raised:
            cur.execute(sql)
        cur.rollback()
    return raised.value


def named(driver, constraint):
    return None if driver == "sqlite3" else constraint


def is_postgres(driver):
    return driver.startswith("psycopg")


def is_mysql(driver):
    return driver.startswith("mysqlclient")


@pytest.mark.parametrize(
    "sql, expected, constraint",
    [
        (
            "INSERT INTO err_parent (id, name) VALUES (3, 'a')",
            exc.UniqueViolation,
            "uq_err_name",
        ),
        (
            "INSERT INTO err_child (id, parent) VALUES (2, 99)",
            exc.ForeignKeyViolation,
            "fk_err_parent",
        ),
        (
            "DELETE FROM err_parent WHERE id = 1",
            exc.ForeignKeyViolation,
            "fk_err_parent",
        ),
        (
            "INSERT INTO err_parent (id, name, age) VALUES (3, 'z', -1)",
            exc.CheckViolation,
            "ck_err_age",
        ),
    ],
    ids=["unique", "foreign_key_insert", "foreign_key_delete", "check"],
)
def test_constraint_violations(db, driver, sql, expected, constraint):
    error = failure(db, driver, sql)
    assert type(error) is expected
    assert isinstance(error, exc.IntegrityError)
    assert error.constraint == named(driver, constraint)
    assert isinstance(error.__cause__, db.conn.driver_error)
    assert not isinstance(error, db.conn.driver_error)


def test_primary_key_is_a_unique_violation(db, driver):
    sql = "INSERT INTO err_parent (id, name) VALUES (1, 'z')"
    assert type(failure(db, driver, sql)) is exc.UniqueViolation


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO err_parent (id, name) VALUES (3, NULL)",
        "INSERT INTO err_parent (id) VALUES (3)",
    ],
    ids=["null", "no_value"],
)
def test_not_null_violation(db, driver, sql):
    error = failure(db, driver, sql)
    assert type(error) is exc.NotNullViolation
    assert error.constraint is None


def test_code(db, driver):
    error = failure(
        db, driver, "INSERT INTO err_parent (id, name) VALUES (3, 'a')"
    )
    assert error.code == UNIQUE_CODES[driver.split("2")[0].split("+")[0]]


@pytest.mark.parametrize(
    "sql",
    ["SELEC 1", "SELECT * FROM err_missing", "SELECT nope FROM err_parent"],
    ids=["syntax", "table", "column"],
)
def test_statement_that_cant_run(db, driver, sql):
    assert type(failure(db, driver, sql)) is exc.ProgrammingError


@pytest.mark.parametrize("driver", SERVERS)
def test_missing_permission(db, driver):
    table = "pg_authid" if is_postgres(driver) else "mysql.user"
    error = failure(db, driver, f"SELECT * FROM {table}")
    assert type(error) is exc.ProgrammingError


@pytest.mark.parametrize("driver", SERVERS)
def test_value_too_long(db, driver):
    sql = "INSERT INTO err_parent (id, name, short) VALUES (3, 'z', 'long')"
    assert type(failure(db, driver, sql)) is exc.DataError


@pytest.mark.parametrize("driver", SERVERS)
def test_value_of_the_wrong_type(db, driver):
    sql = "INSERT INTO err_parent (id, name, age) VALUES (3, 'z', 'abc')"
    assert type(failure(db, driver, sql)) is exc.DataError


@pytest.mark.parametrize("driver", SERVERS)
def test_value_out_of_range(db, driver):
    sql = (
        "SELECT 2147483647 + 1"
        if is_postgres(driver)
        else "SELECT 18446744073709551615 + 1"
    )
    assert type(failure(db, driver, sql)) is exc.DataError


@pytest.mark.parametrize("driver", POSTGRES)
def test_division_by_zero(db, driver):
    assert type(failure(db, driver, "SELECT 1 / 0")) is exc.DataError


@pytest.mark.parametrize("driver", POSTGRES)
def test_exclusion_violation(db, driver):
    with db.cursor as cur:
        cur.execute(
            "CREATE TEMP TABLE err_ex (r int4range, "
            "CONSTRAINT ex_err EXCLUDE USING gist (r WITH &&))"
        )
        cur.execute("INSERT INTO err_ex VALUES ('[1,5]')")
        with pytest.raises(exc.ExclusionViolation) as raised:
            cur.execute("INSERT INTO err_ex VALUES ('[2,3]')")
        cur.rollback()
    assert raised.value.constraint == "ex_err"


@pytest.mark.parametrize("driver", POSTGRES)
def test_raise_exception(db, driver):
    error = failure(db, driver, "DO $$ BEGIN RAISE EXCEPTION 'nope'; END $$")
    assert type(error) is exc.RaisedError
    assert str(error).startswith("nope")


@pytest.mark.parametrize("driver", MYSQL)
def test_signal(db, driver):
    with db.cursor as cur:
        cur.execute("DROP PROCEDURE IF EXISTS err_signal")
        cur.execute(
            "CREATE PROCEDURE err_signal() BEGIN "
            "SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'nope'; END"
        )
    error = failure(db, driver, "CALL err_signal()")
    with db.cursor as cur:
        cur.execute("DROP PROCEDURE err_signal")
    assert type(error) is exc.RaisedError
    assert str(error) == "nope"


def test_sqlite_raise(tmp_path):
    db = Database(f"sqlite3:///{tmp_path / 'raise.db'}")
    with db.cursor as cur:
        cur.execute("CREATE TABLE t (id INT)")
        cur.execute(
            "CREATE TRIGGER tr BEFORE INSERT ON t "
            "BEGIN SELECT RAISE(ABORT, 'nope'); END"
        )
        with pytest.raises(exc.RaisedError, match="nope"):
            cur.execute("INSERT INTO t VALUES (1)")
    db.close()


@pytest.mark.parametrize("driver", BASE)
def test_deadlock(db, driver):
    meet = threading.Barrier(2)
    errors = []

    def lock(first, second):
        with db.cursor as cur:
            try:
                cur.execute(
                    f"UPDATE err_parent SET age = 5 WHERE id = {first}"
                )
                meet.wait(10)
                cur.execute(
                    f"UPDATE err_parent SET age = 5 WHERE id = {second}"
                )
            except exc.DatabaseError as e:
                errors.append(e)
            cur.rollback()

    threads = [
        threading.Thread(target=lock, args=args) for args in ((1, 2), (2, 1))
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert [type(error) for error in errors] == [exc.TransactionConflict]


@pytest.mark.parametrize("driver", BASE)
def test_lock_wait_timeout(db, driver):
    setting = (
        "SET lock_timeout = '50ms'"
        if is_postgres(driver)
        else "SET SESSION innodb_lock_wait_timeout = 1"
    )
    with db.cursor as holder:
        holder.execute("UPDATE err_parent SET age = 5 WHERE id = 1")
        with db.cursor as cur:
            cur.execute(setting)
            with pytest.raises(exc.TransactionConflict):
                cur.execute("UPDATE err_parent SET age = 6 WHERE id = 1")
            cur.rollback()
        holder.rollback()


@pytest.mark.parametrize("driver", DRIVERS)
def test_text_the_connection_cant_encode(db, driver):
    with db.cursor as cur, pytest.raises(exc.DataError) as error:
        cur.query("SELECT :v AS a", v="\ud800").all()
    assert isinstance(error.value.__cause__, UnicodeError)


@pytest.mark.mysql
@pytest.mark.parametrize("driver", ["mysqlclient"])
def test_result_the_connection_cant_decode(db, driver):
    with db.cursor as cur:
        cur.execute("SET character_set_results = latin1")
        with pytest.raises(exc.DataError) as error:
            cur.query("SELECT 'é' AS a").all()
    assert isinstance(error.value.__cause__, UnicodeError)


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_nul_in_a_value(db, driver):
    with db.cursor as cur, pytest.raises(exc.DataError):
        cur.query("SELECT :v AS a", v="a\0b").all()


@pytest.mark.parametrize("driver", [pytest.param("sqlite3", id="sqlite3")])
def test_integer_too_large_for_the_server(db, driver):
    with db.cursor as cur, pytest.raises(exc.DataError):
        cur.query("SELECT :v AS a", v=2**70).all()


@pytest.mark.mysql
@pytest.mark.parametrize("driver", ["mysqlclient", "mysqlclient+pool"])
def test_message_that_isnt_utf8(uri, driver):
    db = Database(uri, charset="latin1")
    with db.cursor as cur:
        cur.execute("CREATE TEMPORARY TABLE latin (a VARCHAR(20) PRIMARY KEY)")
        cur.query("INSERT INTO latin VALUES (:v)", v="é").run()
        with pytest.raises(exc.UniqueViolation) as error:
            cur.query("INSERT INTO latin VALUES (:v)", v="é").run()
    assert error.value.code == 1062
    assert "1062" in str(error.value)
    cause = error.value.__cause__
    assert cause is not None
    assert cause.args[0] == 1062
    assert "1062" in cause.args[1]
    assert "1062" in str(cause)
    db.close()


def test_a_message_without_a_null_stays():
    error = translate(fake("OperationalError", 1062, "the message"), "mysql")
    assert str(error) == "the message"
    assert type(error) is exc.UniqueViolation


def test_value_errors_about_the_sql_stay_value_errors():
    def fail():
        raise ValueError("unsupported format character")

    conn = SimpleNamespace(driver_error=KeyError)
    with pytest.raises(ValueError, match="format character"):
        translating(conn, fail)()


@pytest.mark.parametrize("driver", BASE)
def test_nowait(db, driver):
    with db.cursor as holder:
        holder.execute("UPDATE err_parent SET age = 5 WHERE id = 1")
        with db.cursor as cur:
            with pytest.raises(exc.TransactionConflict):
                cur.execute(
                    "SELECT * FROM err_parent WHERE id = 1 FOR UPDATE NOWAIT"
                )
            cur.rollback()
        holder.rollback()


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
@pytest.mark.parametrize(
    "setting, begin",
    [
        ("idle_session_timeout", False),
        ("idle_in_transaction_session_timeout", True),
    ],
)
def test_server_timeouts(uri, setting, begin):
    db = Database(uri)
    with db.cursor(autocommit=True) as cur:
        cur.execute(f"SET {setting} = 50")
        if begin:
            cur.execute("BEGIN")
        time.sleep(0.2)
        with pytest.raises(exc.ConnectionLost):
            cur.execute("SELECT 1")


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_cursor_on_a_lost_persistent_connection(uri):
    db = Database(uri, persist=True)
    with db.cursor as cur:
        raw_conn = cur.raw_conn
        assert raw_conn is not None
        raw_conn.close()
    with db.cursor as cur:
        assert cur.query("SELECT 1 AS a").value() == 1
    db.close()


def test_sqlite_busy(tmp_path):
    db = Database(f"sqlite3:///{tmp_path / 'busy.db'}", timeout=0)
    with db.cursor as holder:
        holder.execute("CREATE TABLE t (id INT)")
        holder.commit()
        holder.execute("INSERT INTO t VALUES (1)")
        with db.cursor as cur:
            with pytest.raises(exc.TransactionConflict):
                cur.execute("INSERT INTO t VALUES (2)")
        holder.rollback()
    db.close()


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_serialization_failure(db, driver):
    with db.cursor as cur:
        cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
        cur.execute("SELECT * FROM err_parent")
        cur.fetchall()
        with db.cursor as other:
            other.execute("UPDATE err_parent SET age = 5 WHERE id = 1")
            other.commit()
        with pytest.raises(exc.TransactionConflict):
            cur.execute("UPDATE err_parent SET age = 6 WHERE id = 1")
        cur.rollback()


def test_script_name(db, driver):
    values = {"id": 1, "name": "User 1", "email": "x", "city": "y"}
    with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation) as raised:
            cur.users.add(**values).run()
        cur.rollback()
        with pytest.raises(exc.UniqueViolation) as through_db:
            db.users.add(cur, **values).run()
        cur.rollback()
        with pytest.raises(exc.UniqueViolation) as ad_hoc:
            cur.query(
                "INSERT INTO err_parent (id, name) VALUES (1, 'z')"
            ).run()
        cur.rollback()
    assert raised.value.script == "users/add"
    assert through_db.value.script == "users/add"
    assert ad_hoc.value.script is None


def test_executemany(db, driver):
    placeholder = "?" if driver == "sqlite3" else "%s"
    with db.cursor as cur:
        with pytest.raises(exc.UniqueViolation):
            cur.executemany(
                f"INSERT INTO err_parent (id, name) VALUES ({placeholder}, 'z')",
                [(5,), (6,)],
            )
        cur.rollback()


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2"])
def test_callproc(db, driver):
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            cur.callproc("err_missing")
        cur.rollback()


def test_db_execute(db, driver):
    with pytest.raises(exc.UniqueViolation):
        db.execute("INSERT INTO err_parent (id, name) VALUES (1, 'z')")


def deferred_violation(cur, driver):
    if driver == "sqlite3":
        cur.execute("PRAGMA foreign_keys = ON")
        cur.execute("CREATE TEMP TABLE err_p (id INT PRIMARY KEY)")
        cur.execute(
            "CREATE TEMP TABLE err_c (p INT REFERENCES err_p (id) "
            "DEFERRABLE INITIALLY DEFERRED)"
        )
        cur.execute("INSERT INTO err_c VALUES (1)")
        return
    cur.execute(
        "CREATE TEMP TABLE err_d (id INT, CONSTRAINT uq_err_d UNIQUE (id) "
        "DEFERRABLE INITIALLY DEFERRED)"
    )
    cur.execute("INSERT INTO err_d VALUES (1), (1)")


@pytest.mark.parametrize("driver", DEFERRED)
def test_commit(open_db, driver):
    db = open_db()
    with db.cursor as cur:
        deferred_violation(cur, driver)
        with pytest.raises(exc.IntegrityError):
            cur.commit()
        cur.rollback()


@pytest.mark.parametrize("driver", DEFERRED)
def test_commit_of_a_contextcommit_block(open_db, driver):
    db = open_db(contextcommit=True)
    with pytest.raises(exc.IntegrityError):
        with db.cursor as cur:
            deferred_violation(cur, driver)


@pytest.mark.parametrize("driver", DEFERRED)
def test_commit_of_a_transaction_block(open_db, driver):
    db = open_db()
    with db.cursor as cur:
        if driver == "sqlite3":
            cur.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(exc.IntegrityError):
            with cur.transaction():
                deferred_violation(cur, driver)


@pytest.mark.parametrize("driver", DEFERRED)
def test_commit_of_a_block_in_autocommit(open_db, driver):
    db = open_db(autocommit=True)
    with db.cursor as cur:
        if driver == "sqlite3":
            cur.execute("PRAGMA foreign_keys = ON")
        with pytest.raises(exc.IntegrityError):
            with cur.transaction():
                deferred_violation(cur, driver)


def test_statement_in_a_block(db, driver):
    with db.cursor as cur:
        foreign_keys(cur, driver)
        with pytest.raises(exc.UniqueViolation):
            with cur.transaction():
                cur.query(
                    "INSERT INTO err_parent (id, name) VALUES (1, 'z')"
                ).run()


SQLITE_LATE = (
    "WITH c(x) AS (VALUES (1), (-9223372036854775808)) SELECT abs(x) FROM c"
)


def test_fetching(tmp_path):
    db = Database(f"sqlite3:///{tmp_path / 'fetch.db'}", tmp_path)
    (tmp_path / "late.sql").write_text(SQLITE_LATE)
    with db.cursor as cur:
        with pytest.raises(exc.DatabaseError, match="overflow") as raised:
            cur.late().all()
        assert raised.value.script == "late"
        with pytest.raises(exc.DatabaseError, match="overflow"):
            list(cur.late())
        with pytest.raises(exc.DatabaseError, match="overflow"):
            cur.late().many().get(5)
        cur.execute(SQLITE_LATE)
        with pytest.raises(exc.DatabaseError, match="overflow"):
            while cur.fetchone():
                pass
        cur.execute(SQLITE_LATE)
        with pytest.raises(exc.DatabaseError, match="overflow"):
            cur.fetchall()
    db.close()


@pytest.mark.parametrize("driver", POSTGRES)
def test_postgres_stream(db, driver):
    sql = "SELECT 1 / (3 - g) FROM generate_series(1, 5) g"
    rows = []
    with db.cursor as cur:
        with pytest.raises(exc.DataError) as raised:
            for row in cur.query(sql).stream(1):
                rows.append(row[0])
        cur.rollback()
    assert rows == [0, 1]
    assert raised.value.script is None


@pytest.mark.parametrize("driver", MYSQL)
def test_mysql_stream(db, driver):
    with db.cursor as cur:
        cur.execute("DROP FUNCTION IF EXISTS err_late")
        cur.execute(
            "CREATE FUNCTION err_late(x INT) RETURNS INT DETERMINISTIC NO SQL "
            "BEGIN IF x = 3 THEN SIGNAL SQLSTATE '45000' "
            "SET MESSAGE_TEXT = 'late'; END IF; RETURN x; END"
        )
    rows = []
    with db.cursor as cur:
        with pytest.raises(exc.RaisedError, match="late"):
            for row in cur.query(
                "SELECT err_late(id) FROM users ORDER BY id"
            ).stream(1):
                rows.append(row[0])
    with db.cursor as cur:
        cur.execute("DROP FUNCTION err_late")
    assert rows == [1, 2]


def test_stream_that_fails_to_open(db, driver):
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            list(cur.query("SELECT * FROM err_missing").stream())
        cur.rollback()


def test_hook_sees_the_same_error(open_db, driver):
    events = []
    db = open_db(on_execute=events.append)
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError) as raised:
            cur.query("SELECT * FROM err_missing").all()
        cur.rollback()
    assert events[0].error is raised.value


def test_sqlite_driver_method(tmp_path):
    db = Database(f"sqlite3:///{tmp_path / 'script.db'}")
    with db.cursor as cur:
        with pytest.raises(exc.ProgrammingError):
            cur.executescript("SELEC 1;")
    db.close()


def test_script_on_a_dbapi_cursor_raises_the_drivers_error(tmp_path):
    (tmp_path / "broken.sql").write_text("SELEC 1")
    db = Database(util.SQLITE_MEMORY, tmp_path, persist=True)
    raw_cursor = db.conn.conn.cursor()  # ty: ignore[unresolved-attribute]
    with pytest.raises(sqlite3.OperationalError):
        db.broken(raw_cursor).all()
    raw_cursor.close()
    db.close()


@pytest.mark.parametrize("driver", POSTGRES)
def test_driver_details_through_the_cause(db, driver):
    error = failure(
        db, driver, "INSERT INTO err_parent (id, name) VALUES (3, 'a')"
    )
    assert error.__cause__.diag.constraint_name == "uq_err_name"
    assert error.__cause__.diag.table_name == "err_parent"


@pytest.mark.parametrize("driver", MYSQL)
def test_mysql_message_is_text(db, driver):
    error = failure(
        db, driver, "INSERT INTO err_parent (id, name) VALUES (3, 'a')"
    )
    assert str(error).startswith("Duplicate entry")


@pytest.mark.parametrize("driver", MYSQL)
def test_mysql_duplicate_value_cant_fake_the_constraint(db, driver):
    value = "x' for key 'evil"
    with db.cursor as cur:
        cur.query(
            "INSERT INTO err_parent (id, name) VALUES (3, :name)", name=value
        ).run()
        with pytest.raises(exc.UniqueViolation) as raised:
            cur.query(
                "INSERT INTO err_parent (id, name) VALUES (4, :name)",
                name=value,
            ).run()
        cur.rollback()
    assert raised.value.constraint == "uq_err_name"


def test_pickle(db, driver):
    error = failure(
        db, driver, "INSERT INTO err_parent (id, name) VALUES (3, 'a')"
    )
    copy = pickle.loads(pickle.dumps(error))
    assert type(copy) is exc.UniqueViolation
    assert str(copy) == str(error)
    assert copy.code == error.code
    assert copy.constraint == error.constraint
    assert copy.script == error.script


def wrong_port(driver):
    if is_postgres(driver):
        return util.pg_uri(driver).replace(f":{util.PGSQL_PORT}/", ":1/")
    return util.MYSQL_URI.replace(f":{util.MYSQL_PORT}/", ":1/")


@pytest.mark.parametrize("driver", BASE)
def test_failing_connection(driver):
    db = Database(wrong_port(driver))
    with pytest.raises(exc.ConnectionError) as raised:
        with db.cursor:
            pass
    assert not isinstance(raised.value, exc.ConnectionLost)
    assert isinstance(raised.value, exc.DatabaseError)
    assert raised.value.__cause__ is not None
    db.close()


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_invalid_connection_option(driver):
    db = Database(util.pg_uri(driver), no_such_option="1")
    with pytest.raises(exc.ConnectionError, match="no_such_option"):
        with db.cursor:
            pass
    db.close()


@pytest.mark.mysql
def test_mysql_failing_connection_message():
    db = Database(
        f"mysqlclient://wrong_user:wrong@{util.MYSQL_HOST}:"
        f"{util.MYSQL_PORT}/{util.MYSQL_DB}"
    )
    with pytest.raises(exc.ConnectionError) as raised:
        with db.cursor:
            pass
    assert raised.value.code == 1045
    assert str(raised.value).startswith("Access denied")
    db.close()


def test_hierarchy():
    assert issubclass(exc.ConnectionLost, exc.ConnectionError)
    assert issubclass(exc.ConnectionError, exc.DatabaseError)
    for error in (
        exc.UniqueViolation,
        exc.ForeignKeyViolation,
        exc.NotNullViolation,
        exc.CheckViolation,
        exc.ExclusionViolation,
    ):
        assert issubclass(error, exc.IntegrityError)
    for error in (
        exc.IntegrityError,
        exc.DataError,
        exc.ProgrammingError,
        exc.RaisedError,
        exc.TransactionConflict,
    ):
        assert issubclass(error, exc.DatabaseError)


def test_checkout_of_a_broken_connection():
    db = Database(
        f"sqlite3+pool:///{util.SQLITE_FILE}", size=1, overflow=0, timeout=0.1
    )
    with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    raw_conn.close()
    with pytest.raises(exc.DatabaseError):
        with db.cursor(autocommit=True):
            pass
    db.close()


def test_cursor_on_a_closed_connection():
    db = Database(util.SQLITE_MEMORY, persist=True)
    with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    raw_conn.close()
    with pytest.raises(exc.DatabaseError):
        with db.cursor:
            pass
    db.close()


@pytest.mark.mysql
@pytest.mark.parametrize("driver", ["mysqlclient"])
def test_block_on_a_lost_connection(db, driver):
    killer = Database(util.MYSQL_URI)
    with db.cursor as cur:
        cur.execute("SELECT CONNECTION_ID()")
        pid = cur.fetchone()[0]
        killer.execute(f"KILL {pid}")
        with pytest.raises(exc.ConnectionLost):
            with cur.transaction():
                pass
    killer.close()


@pytest.mark.parametrize("driver", POSTGRES)
def test_stream_on_a_closed_connection(db, driver):
    with db.cursor as cur:
        raw_conn = cur.raw_conn
        assert raw_conn is not None
        raw_conn.close()
        with pytest.raises(exc.DatabaseError):
            list(cur.query("SELECT 1").stream())


def fake(name, *args, **attrs):
    error = type(name, (Exception,), {})(*args)
    for key, value in attrs.items():
        setattr(error, key, value)
    return error


@pytest.mark.parametrize(
    "code, expected",
    [
        ("08006", exc.ConnectionLost),
        ("57P01", exc.ConnectionLost),
        ("57P02", exc.ConnectionLost),
        ("57P03", exc.ConnectionLost),
        ("57P05", exc.ConnectionLost),
        ("25P03", exc.ConnectionLost),
        ("25P04", exc.ConnectionLost),
        ("22012", exc.DataError),
        ("23000", exc.IntegrityError),
        ("23P01", exc.ExclusionViolation),
        ("40001", exc.TransactionConflict),
        ("40P01", exc.TransactionConflict),
        ("55P03", exc.TransactionConflict),
        ("42P01", exc.ProgrammingError),
        ("P0001", exc.RaisedError),
        ("25P02", exc.DatabaseError),
    ],
)
@pytest.mark.parametrize("attr", ["sqlstate", "pgcode"])
def test_postgres_codes(attr, code, expected):
    error = translate(
        fake("OperationalError", "m", **{attr: code}), "postgresql"
    )
    assert type(error) is expected
    assert error.code == code


@pytest.mark.parametrize(
    "name, expected",
    [
        ("OperationalError", exc.ConnectionLost),
        ("ProgrammingError", exc.ProgrammingError),
        ("InterfaceError", exc.DatabaseError),
    ],
)
def test_postgres_errors_without_a_code(name, expected):
    error = translate(fake(name, "m\n"), "postgresql")
    assert type(error) is expected
    assert error.code is None
    assert str(error) == "m"


@pytest.mark.parametrize(
    "code, expected",
    [
        (1044, exc.ProgrammingError),
        (1053, exc.ConnectionLost),
        (1216, exc.ForeignKeyViolation),
        (1217, exc.ForeignKeyViolation),
        (1227, exc.ProgrammingError),
        (1264, exc.DataError),
        (1586, exc.UniqueViolation),
        (1690, exc.DataError),
        (1927, exc.ConnectionLost),
        (2006, exc.ConnectionLost),
        (2013, exc.ConnectionLost),
        (2055, exc.ConnectionLost),
        (3572, exc.TransactionConflict),
        (4031, exc.ConnectionLost),
    ],
)
def test_mysql_codes(code, expected):
    error = translate(fake("OperationalError", code, "m"), "mysql")
    assert type(error) is expected
    assert error.code == code
    assert str(error) == "m"


@pytest.mark.parametrize(
    "dialect, args, expected",
    [
        ("postgresql", ["connection already closed"], exc.ConnectionLost),
        ("postgresql", ["cursor already closed"], exc.ConnectionLost),
        ("mysql", [0, "Not connected"], exc.ConnectionLost),
        ("mysql", [0, ""], exc.ConnectionLost),
        ("mysql", [9999, "m"], exc.DatabaseError),
        ("mysql", ["m"], exc.DatabaseError),
    ],
)
def test_interface_errors(dialect, args, expected):
    error = translate(fake("InterfaceError", *args), dialect)
    assert type(error) is expected


@pytest.mark.parametrize(
    "name, expected",
    [
        ("DataError", exc.DataError),
        ("IntegrityError", exc.IntegrityError),
        ("ProgrammingError", exc.ProgrammingError),
        ("OperationalError", exc.DatabaseError),
        ("InternalError", exc.DatabaseError),
    ],
)
def test_unknown_mysql_codes_use_the_drivers_class(name, expected):
    assert type(translate(fake(name, 9999, "m"), "mysql")) is expected


def test_mysql_error_of_the_driver_itself():
    error = translate(fake("ProgrammingError", "not converted"), "mysql")
    assert type(error) is exc.ProgrammingError
    assert error.code is None
    assert str(error) == "not converted"


def test_mysql_error_without_arguments():
    error = translate(fake("OperationalError"), "mysql")
    assert type(error) is exc.DatabaseError
    assert error.code is None


@pytest.mark.parametrize(
    "code, message, constraint",
    [
        (1062, "Duplicate entry 'a' for key 't.uq'", "uq"),
        (1062, "Duplicate entry 'a' for key 'uq'", "uq"),
        (1062, "Doppelter Eintrag 'a' für Schlüssel 'uq'", "uq"),
        (1062, "Duplicate entry 'a' for key 't.PRIMARY'", "PRIMARY"),
        (1062, "no quotes", None),
        (3819, "Check constraint 'ck' is violated.", "ck"),
        (4025, "CONSTRAINT `ck` failed for `d`.`t`", "ck"),
        (
            1452,
            "Cannot add or update a child row: a foreign key constraint "
            "fails (`d`.`t`, CONSTRAINT `f``k` FOREIGN KEY (`p`) REFERENCES "
            "`o` (`id`))",
            "f`k",
        ),
        (1048, "Column 'c' cannot be null", None),
    ],
)
def test_mysql_constraint_names(code, message, constraint):
    error = translate(fake("IntegrityError", code, message), "mysql")
    assert error.constraint == constraint


@pytest.mark.parametrize(
    "code, expected",
    [
        ("SQLITE_BUSY", exc.TransactionConflict),
        ("SQLITE_BUSY_SNAPSHOT", exc.TransactionConflict),
        ("SQLITE_LOCKED_SHAREDCACHE", exc.TransactionConflict),
        ("SQLITE_CONSTRAINT_COMMITHOOK", exc.IntegrityError),
        ("SQLITE_CONSTRAINT_ROWID", exc.UniqueViolation),
        ("SQLITE_ERROR_RETRY", exc.ProgrammingError),
        ("SQLITE_MISMATCH", exc.DataError),
        ("SQLITE_TOOBIG", exc.DataError),
        ("SQLITE_CORRUPT", exc.DatabaseError),
    ],
)
def test_sqlite_codes(code, expected):
    error = translate(
        fake("OperationalError", "m", sqlite_errorname=code), "sqlite"
    )
    assert type(error) is expected
    assert error.code == code
    assert error.constraint is None


def test_sqlite_error_of_the_driver_itself():
    error = translate(fake("ProgrammingError", "closed"), "sqlite")
    assert type(error) is exc.ProgrammingError
    assert error.code is None
