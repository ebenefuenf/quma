import pytest

from .. import (
    APIError,
    Database,
    DatabaseError,
)
from ..pool import Pool
from . import util

ALREADY_OPEN = "already open"
NO_COMMIT = "can't run in a transaction block"
RETURNED = "before the end of its block"
ABORTED = "aborted the transaction"
MYSQL_STREAM = "MySQL can't run"

DRIVERS = [
    pytest.param("sqlite3", id="sqlite3"),
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("psycopg2+pool", marks=pytest.mark.postgres),
    pytest.param("psycopg", marks=pytest.mark.postgres),
    pytest.param("psycopg+pool", marks=pytest.mark.postgres),
    pytest.param("mysqlclient", marks=pytest.mark.mysql),
    pytest.param("mysqlclient+pool", marks=pytest.mark.mysql),
]


def setup_sqlite():
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    db.close()


def prepare(driver):
    """Create the test data and return the URI of ``driver``."""
    if driver == "sqlite3":
        setup_sqlite()
        return util.SQLITE_URI
    if driver.startswith("psycopg"):
        util.setup_pg_db()
        return util.pg_uri(driver)
    util.setup_mysql_db()
    return util.MYSQL_POOL_URI if "+pool" in driver else util.MYSQL_URI


@pytest.fixture(params=DRIVERS)
def open_db(request, named_sqldirs):
    uri = prepare(request.param)
    dbs = []

    def create(**kwargs):
        dbs.append(Database(uri, named_sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        db.close()


@pytest.fixture
def db(open_db):
    return open_db()


@pytest.fixture
def pg(pgdriver, named_sqldirs):
    util.setup_pg_db()
    db = Database(pgdriver.uri, named_sqldirs)
    yield db
    db.close()


@pytest.fixture
def my(named_sqldirs):
    util.setup_mysql_db()
    db = Database(util.MYSQL_URI, named_sqldirs)
    yield db
    db.close()


def move(cur, *ids):
    for id_ in ids:
        cur.query(
            "UPDATE users SET city = 'Moved' WHERE id = :id", id=id_
        ).run()


def moved(db):
    with db.cursor as cur:
        sql = "SELECT id FROM users WHERE city = 'Moved' ORDER BY id"
        return [row[0] for row in cur.query(sql).all()]


def test_commits_at_its_end(db):
    with db.cursor as cur, cur.transaction():
        move(cur, 1)
    assert moved(db) == [1]


def test_rolls_back_on_exception(db):
    with pytest.raises(ValueError, match="in the block"):
        with db.cursor as cur, cur.transaction():
            move(cur, 1)
            raise ValueError("in the block")
    assert moved(db) == []


def test_cursor_runs_several_blocks(db):
    with db.cursor as cur:
        with cur.transaction():
            move(cur, 1)
        with pytest.raises(ValueError):
            with cur.transaction():
                move(cur, 2)
                raise ValueError
        with cur.transaction():
            move(cur, 3)
    assert moved(db) == [1, 3]


def test_nested_rolls_back_only_its_own_work(db):
    with db.cursor as cur, cur.transaction():
        move(cur, 1)
        with pytest.raises(ValueError):
            with cur.transaction():
                move(cur, 2)
                raise ValueError
        with cur.transaction():
            move(cur, 3)
            with cur.transaction():
                move(cur, 4)
    assert moved(db) == [1, 3, 4]


def test_outer_rolls_back_nested(db):
    with pytest.raises(ValueError):
        with db.cursor as cur, cur.transaction():
            move(cur, 1)
            with cur.transaction():
                move(cur, 2)
            raise ValueError
    assert moved(db) == []


def test_nested_as_first_statement_of_outer(db):
    # The driver sees no open transaction when the nested block starts.
    with pytest.raises(ValueError):
        with db.cursor as cur, cur.transaction():
            with cur.transaction():
                move(cur, 1)
            raise ValueError
    assert moved(db) == []


def test_block_without_statements(db):
    with db.cursor as cur:
        with cur.transaction():
            with cur.transaction():
                pass
        with cur.transaction():
            move(cur, 1)
    assert moved(db) == [1]


def test_refuses_open_transaction(db):
    with db.cursor as cur:
        move(cur, 1)
        with pytest.raises(APIError, match=ALREADY_OPEN):
            with cur.transaction():
                pytest.fail("The block must not run")
        cur.rollback()
        with cur.transaction():
            move(cur, 2)
    assert moved(db) == [2]


def test_starts_after_commit(db):
    with db.cursor as cur:
        move(cur, 1)
        cur.commit()
        with cur.transaction():
            move(cur, 2)
    assert moved(db) == [1, 2]


def test_commit_and_rollback_refused_inside(db):
    with db.cursor as cur, cur.transaction():
        move(cur, 1)
        with pytest.raises(APIError, match=NO_COMMIT):
            cur.commit()
        with pytest.raises(APIError, match=NO_COMMIT):
            cur.rollback()
    assert moved(db) == [1]


def test_commit_works_after_the_block(db):
    with db.cursor as cur:
        with cur.transaction():
            move(cur, 1)
        move(cur, 2)
        cur.commit()
    assert moved(db) == [1, 2]


def test_keeps_unread_result(db):
    with db.cursor as cur, cur.transaction():
        query = cur.users.all().run()
        with cur.transaction():
            pass
        assert len(query.all()) == 7


def check_autocommit(db, cursor):
    with cursor() as cur:
        assert cur.users.all().all()
        move(cur, 1)
        with pytest.raises(ValueError):
            with cur.transaction():
                move(cur, 2)
                raise ValueError
        with cur.transaction():
            move(cur, 3)
            with pytest.raises(ValueError):
                with cur.transaction():
                    move(cur, 4)
                    raise ValueError
            assert moved_on(cur) == [1, 3]
        move(cur, 5)
    assert moved(db) == [1, 3, 5]


def moved_on(cur):
    sql = "SELECT id FROM users WHERE city = 'Moved' ORDER BY id"
    return [row[0] for row in cur.query(sql).all()]


def test_autocommit_cursor(db):
    check_autocommit(db, lambda: db.cursor(autocommit=True))


def test_autocommit_call_wrapper(db):
    check_autocommit(db, lambda: db(autocommit=True).cursor)


def test_autocommit_database(open_db):
    db = open_db(autocommit=True)
    check_autocommit(db, lambda: db.cursor)


def test_autocommit_database_needs_no_commit(open_db):
    db = open_db(autocommit=True)
    with db.cursor as cur:
        move(cur, 1)
    assert moved(db) == [1]
    cur = db.cursor()
    try:
        move(cur, 2)
    finally:
        cur.close()
    assert moved(db) == [1, 2]
    carrier = object()
    try:
        with db(carrier).cursor as cur:
            move(cur, 3)
    finally:
        db.release(carrier)
    assert moved(db) == [1, 2, 3]


def test_default_database_keeps_rolling_back(db):
    with db.cursor as cur:
        move(cur, 1)
    assert moved(db) == []


def test_carried_cursors_share_a_block(db):
    carrier = object()
    try:
        with db(carrier).cursor as cur, cur.transaction():
            move(cur, 1)
            with db(carrier).cursor as other:
                with pytest.raises(ValueError):
                    with other.transaction():
                        move(other, 2)
                        raise ValueError
                move(other, 3)
                with pytest.raises(APIError, match=NO_COMMIT):
                    other.commit()
    finally:
        db.release(carrier)
    assert moved(db) == [1, 3]


def test_carried_contextcommit_leaves_it_to_the_block(open_db):
    db = open_db(contextcommit=True)
    carrier = object()
    try:
        with pytest.raises(ValueError):
            with db(carrier).cursor as cur, cur.transaction():
                with db(carrier).cursor as other:
                    move(other, 1)
                raise ValueError
    finally:
        db.release(carrier)
    assert moved(db) == []


def test_contextcommit_cursor(open_db):
    db = open_db(contextcommit=True)
    with db.cursor as cur:
        with cur.transaction():
            move(cur, 1)
        with pytest.raises(ValueError):
            with cur.transaction():
                move(cur, 2)
                raise ValueError
        move(cur, 3)
    assert moved(db) == [1, 3]


def test_connection_returned_in_block(db):
    with pytest.raises(APIError, match=RETURNED):
        with db.cursor as cur, cur.transaction():
            move(cur, 1)
            cur.close()
    assert moved(db) == []


def test_connection_returned_keeps_block_error(db):
    with pytest.raises(ValueError):
        with db.cursor as cur, cur.transaction():
            cur.close()
            raise ValueError


@pytest.mark.parametrize(
    "driver",
    [
        pytest.param("sqlite3"),
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ],
)
def test_persistent_connection_returned_by_other_cursor(driver, named_sqldirs):
    db = Database(prepare(driver), named_sqldirs, persist=True)
    with pytest.raises(APIError, match=RETURNED):
        with db.cursor as cur, cur.transaction():
            move(cur, 1)
            with db.cursor:
                pass
    assert moved(db) == []
    db.close()


def test_can_start_again_after_a_block(db):
    with pytest.raises(ValueError):
        with db.cursor as cur, cur.transaction():
            raise ValueError
    with db.cursor as cur, cur.transaction():
        move(cur, 1)
    assert moved(db) == [1]


@pytest.mark.parametrize("driver", ["psycopg2+pool", "psycopg+pool"])
@pytest.mark.postgres
def test_pool_gets_its_connection_back(driver, named_sqldirs):
    db = Database(
        prepare(driver), named_sqldirs, size=1, overflow=0, timeout=1
    )
    with pytest.raises(ValueError):
        with db.cursor as cur, cur.transaction():
            raise ValueError
    assert isinstance(db.conn, Pool)
    assert db.conn.checkedout == 0
    db.close()


def test_sqlite_read_opens_no_transaction():
    setup_sqlite()
    db = Database(util.SQLITE_URI)
    with db.cursor as cur:
        assert cur.query("SELECT * FROM users").all()
        with cur.transaction():
            move(cur, 1)
    assert moved(db) == [1]
    db.close()


@pytest.mark.postgres
def test_postgres_read_opens_transaction(pg):
    with pg.cursor as cur:
        assert cur.query("SELECT 1 AS one").value() == 1
        with pytest.raises(APIError, match=ALREADY_OPEN):
            with cur.transaction():
                pytest.fail("The block must not run")


@pytest.mark.postgres
def test_postgres_failed_statement_prevents_commit(pg, pgdriver):
    with pytest.raises(APIError, match=ABORTED):
        with pg.cursor as cur, cur.transaction():
            move(cur, 1)
            with pytest.raises(DatabaseError):
                cur.query("SELECT 1 / 0").run()
    assert moved(pg) == []


@pytest.mark.postgres
def test_postgres_nested_recovers_from_failed_statement(pg, pgdriver):
    with pg.cursor as cur, cur.transaction():
        move(cur, 1)
        with pytest.raises(DatabaseError):
            with cur.transaction():
                move(cur, 2)
                cur.query("SELECT 1 / 0").run()
        with pytest.raises(APIError, match=ABORTED):
            with cur.transaction():
                move(cur, 3)
                with pytest.raises(DatabaseError):
                    cur.query("SELECT 1 / 0").run()
        move(cur, 4)
    assert moved(pg) == [1, 4]


@pytest.mark.postgres
def test_postgres_stream_in_block_on_autocommit_cursor(pg):
    with pg.cursor(autocommit=True) as cur:
        with pytest.raises(APIError, match="in transactions only"):
            next(cur.users.all().stream())
        with cur.transaction():
            assert len(list(cur.users.all().stream(3))) == 7


@pytest.mark.postgres
def test_postgres_stream_ends_with_its_block(pg, pgdriver):
    with pg.cursor as cur:
        with cur.transaction():
            rows = cur.users.all().stream(1)
            next(rows)
        with pytest.raises(DatabaseError):
            next(rows)
        cur.rollback()
        assert cur.query("SELECT 1 AS one").value() == 1


@pytest.mark.postgres
def test_postgres_stream_survives_nested_rollback(pg):
    with pg.cursor as cur, cur.transaction():
        rows = cur.users.all().stream(1)
        first = next(rows)
        with pytest.raises(ValueError):
            with cur.transaction():
                move(cur, 1)
                raise ValueError
        assert next(rows) != first
        rows.close()
    assert moved(pg) == []


@pytest.mark.postgres
def test_postgres_stream_ends_with_rolled_back_nested_block(pg, pgdriver):
    with pytest.raises(APIError, match=ABORTED):
        with pg.cursor as cur, cur.transaction():
            with pytest.raises(ValueError):
                with cur.transaction():
                    rows = cur.users.all().stream(1)
                    next(rows)
                    raise ValueError
            with pytest.raises(DatabaseError):
                next(rows)


@pytest.mark.mysql
def test_mysql_detects_open_transaction(my):
    with my.cursor as cur:
        assert cur.query("SELECT 1 AS one").value() == 1
        with cur.transaction():
            pass
        assert cur.query("SELECT * FROM users").all()
        with pytest.raises(APIError, match=ALREADY_OPEN):
            with cur.transaction():
                pytest.fail("The block must not run")
        cur.rollback()
        move(cur, 1)
        with pytest.raises(APIError, match=ALREADY_OPEN):
            with cur.transaction():
                pytest.fail("The block must not run")


@pytest.mark.mysql
def test_mysql_open_stream_refuses_block(my):
    with my.cursor as cur:
        rows = cur.users.all().stream(1)
        next(rows)
        with pytest.raises(APIError, match=MYSQL_STREAM):
            with cur.transaction():
                pytest.fail("The block must not run")
        rows.close()


@pytest.mark.mysql
def test_mysql_stream_prevents_commit_and_block_rolls_back(my):
    with pytest.raises(APIError, match=MYSQL_STREAM):
        with my.cursor as cur, cur.transaction():
            move(cur, 1)
            rows = cur.users.all().stream(1)
            next(rows)
    assert moved(my) == []
    assert rows is not None


@pytest.mark.mysql
def test_mysql_exception_with_open_stream_rolls_back(my):
    carrier = object()
    try:
        with pytest.raises(ValueError):
            with my(carrier).cursor as cur, cur.transaction():
                move(cur, 1)
                rows = cur.users.all().stream(1)
                next(rows)
                raise ValueError
        # The carrier keeps the connection, so the block itself rolled back.
        with my(carrier).cursor as cur:
            assert moved_on(cur) == []
    finally:
        my.release(carrier)
    assert rows is not None


def committed_ids(driver):
    """What another connection sees."""
    other = Database(util.pg_uri(driver))
    with other.cursor as cur:
        return [row[0] for row in cur.query("SELECT a FROM reset_test").all()]


@pytest.fixture
def reset_table(pgdriver):
    db = Database(pgdriver.uri)
    db.execute("DROP TABLE IF EXISTS reset_test")
    db.execute("CREATE TABLE reset_test (a integer)")
    yield pgdriver.name
    db.execute("DROP TABLE reset_test")


@pytest.mark.postgres
def test_pool_ends_a_block_a_closed_cursor_left_open(reset_table):
    db = Database(
        util.pg_uri(f"{reset_table}+pool"), size=1, overflow=0, autocommit=True
    )
    cur = db.cursor()
    with pytest.raises(APIError, match=RETURNED), cur.transaction():
        cur.query("INSERT INTO reset_test VALUES (1)").run()
        cur.close()

    with db.cursor as cur:
        cur.query("INSERT INTO reset_test VALUES (2)").run()
    db.close()
    assert committed_ids(reset_table) == [2]


@pytest.mark.postgres
@pytest.mark.parametrize(
    "options", [{"size": 1, "overflow": 0}, {"persist": True}]
)
def test_connection_ends_a_transaction_begun_in_autocommit(
    reset_table, options
):
    scheme = f"{reset_table}+pool" if "size" in options else reset_table
    db = Database(util.pg_uri(scheme), **options)
    with db.cursor(autocommit=True) as cur:
        cur.execute("BEGIN")
        cur.execute("INSERT INTO reset_test VALUES (1)")

    with db.cursor(autocommit=True) as cur:
        cur.execute("INSERT INTO reset_test VALUES (2)")
    db.close()
    assert committed_ids(reset_table) == [2]
