from types import SimpleNamespace

import pytest

from .. import (
    Database,
    ProgrammingError,
    connect,
)
from . import util
from .test_conn import (
    connect_pool,
    is_closed,
)


@pytest.fixture(
    params=[
        "sqlite3",
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    name = request.param
    calls = []
    if name == "sqlite3":
        spec = dict(
            uri=util.SQLITE_URI,
            pool_uri=f"sqlite3+pool:///{util.SQLITE_FILE}",
            setup="PRAGMA foreign_keys = ON",
            check="PRAGMA foreign_keys",
            value=1,
        )
    elif name == "mysqlclient":
        spec = dict(
            uri=util.MYSQL_URI,
            pool_uri=util.MYSQL_POOL_URI,
            setup="SET @quma_on_connect = 7",
            check="SELECT @quma_on_connect",
            value=7,
        )
    else:
        pytest.importorskip(name)
        spec = dict(
            uri=util.pg_uri(name),
            pool_uri=util.pg_uri(f"{name}+pool"),
            setup="SET application_name = 'quma_on_connect'",
            check="SHOW application_name",
            value="quma_on_connect",
        )

    def hook(conn):
        calls.append(conn)
        cur = conn.cursor()
        cur.execute(spec["setup"])
        cur.close()

    return SimpleNamespace(name=name, calls=calls, hook=hook, **spec)


def test_pool_runs_it_once_per_connection(driver):
    pool = connect_pool(driver.pool_uri, size=2, on_connect=driver.hook)
    assert driver.calls == []
    first = pool.get()
    assert driver.calls == [first]
    pool.put(first)
    assert pool.get() is first
    assert driver.calls == [first]
    second = pool.get()
    assert driver.calls == [first, second]
    pool.put(first)
    pool.put(second)
    pool.close()


def test_every_cursor_runs_it_without_a_pool(driver):
    db = Database(driver.uri, on_connect=driver.hook)
    for count in (1, 2):
        with db.cursor as cur:
            assert cur.query(driver.check).value() == driver.value
        assert len(driver.calls) == count
    db.close()


def test_persistent_connection_runs_it_once(driver):
    db = Database(driver.uri, persist=True, on_connect=driver.hook)
    assert len(driver.calls) == 1
    for _ in range(2):
        with db.cursor as cur:
            assert cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 1
    db.close()


def test_persistent_reconnect_runs_it_again(driver):
    db = Database(
        driver.uri, persist=True, pessimistic=True, on_connect=driver.hook
    )
    driver.calls[0].close()
    with db.cursor as cur:
        assert cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 2
    db.close()


def test_pool_replacement_runs_it_again(driver):
    pool = connect_pool(
        driver.pool_uri, size=1, pessimistic=True, on_connect=driver.hook
    )
    first = pool.get()
    pool.put(first)
    first.close()
    second = pool.get()
    assert second is not first
    assert driver.calls == [first, second]
    pool.put(second)
    pool.close()


def test_its_settings_survive_returning_the_connection(driver):
    db = Database(driver.pool_uri, size=1, on_connect=driver.hook)
    for _ in range(2):
        with db.cursor as cur:
            assert cur.query(driver.check).value() == driver.value
    assert len(driver.calls) == 1
    db.close()


def test_transaction_block_can_start_right_after_it(driver):
    db = Database(driver.pool_uri, size=1, on_connect=driver.hook)
    with db.cursor as cur, cur.transaction():
        assert cur.query(driver.check).value() == driver.value
    db.close()


def test_it_runs_before_autocommit_applies(driver):
    modes = []

    def hook(conn):
        modes.append(pool.in_autocommit(conn))
        driver.hook(conn)

    pool = connect_pool(driver.pool_uri, size=1, on_connect=hook)
    raw = pool.get(autocommit=True)
    assert modes == [False]
    assert pool.in_autocommit(raw)
    pool.put(raw)
    pool.close()


def test_autocommit_left_on_doesnt_reach_the_cursor(driver):
    def hook(conn):
        pool._conn.enable_autocommit_if(True, conn)

    pool = connect_pool(driver.pool_uri, size=1, on_connect=hook)
    raw = pool.get()
    assert not pool.in_autocommit(raw)
    pool.put(raw)
    pool.close()


def test_exception_closes_the_connection_and_frees_the_slot(driver):
    def hook(conn):
        driver.calls.append(conn)
        if len(driver.calls) == 1:
            raise ZeroDivisionError

    pool = connect_pool(
        driver.pool_uri, size=1, overflow=0, timeout=0.01, on_connect=hook
    )
    with pytest.raises(ZeroDivisionError):
        pool.get()
    assert is_closed(driver.calls[0])
    assert pool.checkedout == 0
    raw = pool.get()
    assert raw is driver.calls[1]
    pool.put(raw)
    pool.close()


def test_driver_error_becomes_quma_exception(driver):
    def hook(conn):
        driver.calls.append(conn)
        cur = conn.cursor()
        cur.execute("SELECT * FROM quma_table_that_does_not_exist")

    pool = connect_pool(driver.pool_uri, size=1, overflow=0, on_connect=hook)
    with pytest.raises(ProgrammingError) as info:
        pool.get()
    assert isinstance(info.value.__cause__, pool.driver_error)
    assert is_closed(driver.calls[0])
    assert pool.checkedout == 0
    pool.close()


def test_its_statements_are_not_reported(driver):
    events = []
    db = Database(driver.uri, on_connect=driver.hook, on_execute=events.append)
    with db.cursor as cur:
        cur.query(driver.check).value()
    assert [event.sql for event in events] == [driver.check]
    db.close()


def test_plain_database_refuses_an_async_function():
    async def hook(conn):
        pass

    with pytest.raises(TypeError, match="on_connect"):
        Database(util.SQLITE_URI, on_connect=hook)
    with pytest.raises(TypeError, match="on_connect"):
        connect(util.SQLITE_URI, on_connect=hook)


@pytest.mark.postgres
def test_psycopg_types_registered_on_the_connection():
    psycopg = pytest.importorskip("psycopg")

    class Upper(psycopg.adapt.Loader):
        def load(self, data):
            return bytes(data).decode().upper()

    def hook(conn):
        conn.adapters.register_loader("text", Upper)

    db = Database(util.pg_uri("psycopg+pool"), on_connect=hook)
    with db.cursor as cur:
        assert cur.query("SELECT 'quma'::text").value() == "QUMA"
    db.close()


@pytest.mark.postgres
def test_psycopg2_types_registered_on_the_connection():
    psycopg2 = pytest.importorskip("psycopg2")
    upper = psycopg2.extensions.new_type(
        (25,), "UPPER", lambda value, cursor: value.upper()
    )

    def hook(conn):
        psycopg2.extensions.register_type(upper, conn)

    db = Database(util.pg_uri("psycopg2+pool"), on_connect=hook)
    with db.cursor as cur:
        assert cur.query("SELECT 'quma'::text").value() == "QUMA"
    db.close()
