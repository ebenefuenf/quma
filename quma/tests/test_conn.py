import queue
import sqlite3
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from .. import (
    Database,
    conn,
    connect,
    exc,
)
from .. import pool as pool_module
from ..pool import Pool
from . import util


def connect_pool(uri, **kwargs):
    pool = connect(uri, **kwargs)
    assert isinstance(pool, Pool)
    return pool


def connect_single(uri, **kwargs):
    single = connect(uri, **kwargs)
    assert isinstance(single, conn.Connection)
    return single


def get_cursor_mock(exception):
    def cursor():
        m = Mock()
        m.execute = Mock()
        m.execute.side_effect = exception
        return m

    return cursor


def test_base_connection(pgdburl):
    # We test with a PostgreSQL url but any other would do
    kwargs = dict(persist=True)
    cn = conn.Connection(pgdburl, kwargs)
    assert kwargs.get("persist") is None
    assert cn.database == util.PGSQL_DB
    assert cn.username == util.PGSQL_USER
    assert cn.password == util.PGSQL_PASS
    assert cn.url == pgdburl
    c = Mock()
    cn.conn = c
    with pytest.raises(NotImplementedError):
        cn.check()
    cn.close()
    cn.close(c)
    assert c.close.call_count == 2


def test_failing_check():
    conn = connect_single(util.SQLITE_MEMORY, persist=True, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(sqlite3.ProgrammingError)
    with pytest.raises(exc.ConnectionLost):
        conn._check(connmock)
    connmock.cursor = get_cursor_mock(sqlite3.OperationalError)
    with pytest.raises(exc.ConnectionLost):
        conn._check(connmock)
    conn.close()


def test_persistent_pessimistic(dbpess):
    with dbpess.cursor as cursor:
        cn = cursor.raw_conn
    with dbpess.cursor as cursor:
        assert cn is cursor.raw_conn
    dbpess.conn._check = Mock()
    dbpess.conn._check.side_effect = exc.ConnectionLost
    with dbpess.cursor as cursor:
        assert cn is not cursor.raw_conn
    with pytest.raises(sqlite3.ProgrammingError):
        cn.execute("SELECT 1")


def pool_overflow_counting(uri):
    conn = connect_pool(uri, size=1, overflow=4)
    cn1 = conn.get()
    cn2 = conn.get()
    cn3 = conn.get()
    assert conn.overflow == 2
    conn.put(cn1)
    # Queue not full yet, overflow does not decrease
    assert conn.overflow == 2
    conn.put(cn2)
    # Queue is full now, overflow must be lower
    assert conn.overflow == 1
    cn4 = conn.get()
    cn5 = conn.get()
    assert conn.overflow == 2
    conn._conn.get = Mock()
    conn._conn.get.side_effect = ValueError
    with pytest.raises(ValueError):
        conn.get()
    assert conn.overflow == 2
    for cn in (cn3, cn4, cn5):
        conn.put(cn)
    conn.close()


@pytest.mark.postgres
def test_postgres_pool_overflow_counting(pgdriver):
    pool_overflow_counting(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pool_overflow_counting():
    pool_overflow_counting(util.MYSQL_POOL_URI)


def non_persistent(uri, connection, pessimistic):
    conn = connect_single(uri, pessimistic=pessimistic)
    cn1 = conn.get()
    assert cn1.closed == 0
    with pytest.raises(AttributeError):
        conn.conn
    assert type(cn1) is connection
    cn2 = conn.get()
    assert cn1 != cn2
    conn.put(cn1)
    assert cn1.closed == 1
    assert cn2.closed == 0
    conn.put(cn2)
    assert cn2.closed == 1
    conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_non_persistent(pgdriver, pessimistic):
    non_persistent(pgdriver.uri, pgdriver.connection, pessimistic)


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_non_persistent(pessimistic):
    from MySQLdb.connections import Connection

    non_persistent(util.MYSQL_URI, Connection, pessimistic)


def persistent(uri, connection):
    conn = connect_single(uri, persist=True)
    cn1 = conn.get()
    assert cn1.closed == 0
    assert conn.conn == cn1
    assert type(cn1) is connection
    conn.put(cn1)
    assert cn1.closed == 0
    cn2 = conn.get()
    assert cn1 == cn2
    assert conn.conn is not None
    conn.close()
    assert cn1.closed == 1
    assert cn2.closed == 1
    with pytest.raises(AttributeError):
        conn.conn
    conn.close()


@pytest.mark.postgres
def test_postgres_persistent(pgdriver):
    persistent(pgdriver.uri, pgdriver.connection)


@pytest.mark.mysql
def test_mysql_persistent():
    from MySQLdb.connections import Connection

    persistent(util.MYSQL_URI, Connection)


def pool(uri, pessimistic, connection):
    from .. import pool

    conn = connect(uri, pessimistic=pessimistic)
    assert type(conn) is pool.Pool
    assert conn.size == 5
    cn1 = conn.get()
    assert conn.overflow == -4
    cn2 = conn.get()
    assert conn.overflow == -3
    assert type(cn1) is connection
    assert type(cn2) is connection
    assert cn1 != cn2
    conn.put(cn1)
    conn.put(cn2)
    assert conn.status().startswith("Pool size: 5 Connections")
    assert conn.checkedin == 2
    cn3 = conn.get()
    assert conn.checkedin == 1
    assert cn3 == cn1
    conn.put(cn3)
    conn.close()
    assert conn.checkedin == 0


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_pool(pgdriver, pessimistic):
    pool(pgdriver.pool_uri, pessimistic, pgdriver.connection)


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_pool(pessimistic):
    from MySQLdb.connections import Connection

    pool(util.MYSQL_POOL_URI, pessimistic, Connection)


def pessimistic_failure(uri):
    conn = connect_pool(uri, size=1, overflow=-1, pessimistic=True)
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 == c2
    conn.put(c2)
    conn._conn.check = Mock()
    conn._conn.check.side_effect = exc.ConnectionLost
    c1 = conn.get()
    conn.put(c1)
    c2 = conn.get()
    assert c1 != c2
    conn.put(c2)
    conn.close()


def pool_reuse_autocommit(uri, pessimistic, is_autocommit):
    conn = connect(uri, size=1, pessimistic=pessimistic)
    for autocommit in (False, True, False):
        raw_conn = conn.get(autocommit=autocommit)
        assert is_autocommit(raw_conn) is autocommit
        conn.put(raw_conn)
    conn.close()


@pytest.mark.postgres
@pytest.mark.parametrize("pessimistic", [False, True])
def test_postgres_pool_reuse_autocommit(pgdriver, pessimistic):
    pool_reuse_autocommit(
        pgdriver.pool_uri, pessimistic, lambda conn: conn.autocommit
    )


@pytest.mark.mysql
@pytest.mark.parametrize("pessimistic", [False, True])
def test_mysql_pool_reuse_autocommit(pessimistic):
    pool_reuse_autocommit(
        util.MYSQL_POOL_URI, pessimistic, lambda conn: conn.get_autocommit()
    )


def persistent_pessimistic_autocommit(uri, is_autocommit):
    db = Database(uri, persist=True, pessimistic=True)
    for autocommit in (False, True, False):
        with db(autocommit=autocommit).cursor as cursor:
            assert is_autocommit(cursor.raw_conn) is autocommit
    db.close()


@pytest.mark.postgres
def test_postgres_persistent_pessimistic_autocommit(pgdriver):
    persistent_pessimistic_autocommit(
        pgdriver.uri, lambda conn: conn.autocommit
    )


@pytest.mark.mysql
def test_mysql_persistent_pessimistic_autocommit():
    persistent_pessimistic_autocommit(
        util.MYSQL_URI, lambda conn: conn.get_autocommit()
    )


@pytest.mark.postgres
def test_postgres_pessimistic_failure(pgdriver):
    pessimistic_failure(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pessimistic_failure():
    pessimistic_failure(util.MYSQL_POOL_URI)


def persistent_replaces_closed(uri):
    conn = connect_single(uri, persist=True, pessimistic=True)
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    cn2 = conn.get()
    assert cn2 is not cn1
    conn.put(cn2)
    assert conn.get() is cn2
    conn.put(cn2)
    conn.close()


@pytest.mark.postgres
def test_postgres_persistent_replaces_closed(pgdriver):
    persistent_replaces_closed(pgdriver.uri)


@pytest.mark.mysql
def test_mysql_persistent_replaces_closed():
    persistent_replaces_closed(util.MYSQL_URI)


def pool_replaces_closed(uri):
    conn = connect_pool(uri, size=1, overflow=0, pessimistic=True)
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    cn2 = conn.get()
    assert cn2 is not cn1
    conn.put(cn2)
    assert conn.checkedout == 0
    assert conn.get() is cn2
    conn.put(cn2)
    conn.close()


@pytest.mark.postgres
def test_postgres_pool_replaces_closed(pgdriver):
    pool_replaces_closed(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_pool_replaces_closed():
    pool_replaces_closed(util.MYSQL_POOL_URI)


@pytest.mark.postgres
def test_postgres_failed_cursor_returns_connection(pgdriver):
    db = Database(pgdriver.pool_uri, size=1, overflow=0, timeout=0.1)
    with db.cursor as cur:
        raw_conn = cur.raw_conn
    assert raw_conn is not None
    raw_conn.close()
    carrier = SimpleNamespace()
    with pytest.raises(exc.DatabaseError):
        with db(carrier).cursor:
            pass
    assert db.heap.get(carrier).conn is None
    with db.cursor as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    db.close()


def test_pool_discards_broken_connection():
    conn = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}", size=1, overflow=0, timeout=0.01
    )
    cn1 = conn.get()
    cn1.close()
    conn.put(cn1)
    assert conn.checkedout == 0
    cn2 = conn.get()
    assert cn2 is not cn1
    conn.put(cn2)
    conn.close()


def test_pool_failed_replacement(monkeypatch):
    conn = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}",
        size=1,
        overflow=0,
        timeout=0.01,
        pessimistic=True,
    )
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    monkeypatch.setattr(
        conn._conn, "create_conn", Mock(side_effect=exc.ConnectionError)
    )
    with pytest.raises(exc.ConnectionError):
        conn.get()
    monkeypatch.undo()
    assert conn.checkedout == 0
    cn2 = conn.get()
    conn.put(cn2)
    conn.close()


def test_pool_waiter_wakes_when_broken_connection_is_discarded():
    conn = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}",
        size=1,
        overflow=0,
        timeout=5,
        check_same_thread=False,
    )
    cn1 = conn.get()
    results = queue.Queue()

    def wait():
        try:
            results.put(conn.get())
        except exc.TimeoutError as e:
            results.put(e)

    waiter = threading.Thread(target=wait)
    waiter.start()
    time.sleep(0.05)
    cn1.close()
    conn.put(cn1)
    # Waking only at the timeout would be too late.
    waiter.join(1)
    assert not waiter.is_alive()
    cn2 = results.get()
    assert not isinstance(cn2, Exception)
    assert cn2 is not cn1
    conn.put(cn2)
    assert conn.checkedout == 0
    conn.close()


def test_pool_failed_autocommit_frees_slot():
    conn = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}", size=1, overflow=0, timeout=0.01
    )
    cn1 = conn.get()
    conn.put(cn1)
    cn1.close()
    with pytest.raises(sqlite3.ProgrammingError):
        conn.get(autocommit=True)
    assert conn.checkedout == 0
    cn2 = conn.get()
    conn.put(cn2)
    conn.close()


def test_pool_closes_connections_returned_after_close():
    conn = connect_pool(f"sqlite3+pool:///{util.SQLITE_FILE}", size=1)
    cn = conn.get()
    conn.close()
    conn.put(cn)
    assert conn.checkedin == 0
    assert conn.checkedout == 0
    with pytest.raises(sqlite3.ProgrammingError):
        cn.execute("SELECT 1")


def is_closed(raw):
    if isinstance(raw, sqlite3.Connection):
        try:
            raw.execute("SELECT 1")
        except sqlite3.ProgrammingError:
            return True
        return False
    # MySQLdb has open, psycopg2 and psycopg have closed.
    return not raw.open if hasattr(raw, "open") else bool(raw.closed)


@pytest.fixture(
    params=[
        "sqlite3",
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ]
)
def limited(request, clock):
    uri = {
        "sqlite3": f"sqlite3+pool:///{util.SQLITE_FILE}",
        "mysqlclient": util.MYSQL_POOL_URI,
    }.get(request.param) or util.pg_uri(f"{request.param}+pool")
    pools = []

    def create(**kwargs):
        pools.append(connect_pool(uri, **kwargs))
        return pools[-1]

    yield create
    for pool in pools:
        pool.close()


def test_pool_replaces_connection_past_max_lifetime(limited, clock):
    pool = limited(size=1, overflow=0, timeout=0.01, max_lifetime=100)
    raw = pool.get()
    pool.put(raw)
    clock.now += 94
    assert pool.get() is raw
    pool.put(raw)
    clock.now += 6
    fresh = pool.get()
    assert fresh is not raw
    assert is_closed(raw)
    assert pool.checkedout == 1
    assert pool.checkedin == 0
    pool.put(fresh)
    assert pool.checkedin == 1
    assert pool.checkedout == 0


def test_pool_closes_returned_connection_past_max_lifetime(limited, clock):
    pool = limited(size=1, overflow=0, timeout=0.01, max_lifetime=100)
    raw = pool.get()
    clock.now += 100
    assert not is_closed(raw)
    pool.put(raw)
    assert is_closed(raw)
    assert pool.checkedin == 0
    assert pool.checkedout == 0
    pool.put(pool.get())
    assert pool.checkedin == 1


def test_pool_lifetimes_differ_but_stay_within_max_lifetime(clock):
    pool = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}", size=40, max_lifetime=100
    )
    raws = [pool.get() for _ in range(40)]
    for raw in raws:
        pool.put(raw)
    clock.now += 97.5
    survivor = pool.get()
    assert survivor in raws
    assert 0 < sum(is_closed(raw) for raw in raws) < 40
    pool.put(survivor)
    clock.now += 2.5
    fresh = pool.get()
    assert fresh not in raws
    assert all(is_closed(raw) for raw in raws)
    pool.put(fresh)
    pool.close()


def test_pool_closes_every_idle_connection_past_max_lifetime(limited, clock):
    pool = limited(size=2, max_lifetime=100, max_idle=1000)
    older = pool.get()
    clock.now += 50
    newer = pool.get()
    pool.put(older)
    pool.put(newer)
    clock.now += 50
    assert pool.get() is newer
    assert is_closed(older)
    pool.put(newer)
    assert pool.checkedin == 1


@pytest.mark.parametrize("limits", [{}, {"max_lifetime": 100}])
def test_pool_reuses_in_order_of_return_without_max_idle(limited, limits):
    pool = limited(size=2, **limits)
    first, second = pool.get(), pool.get()
    pool.put(first)
    pool.put(second)
    assert pool.get() is first
    assert pool.get() is second
    pool.put(first)
    pool.put(second)


def test_pool_reuses_most_recent_with_max_idle(limited):
    pool = limited(size=2, max_idle=100)
    first, second = pool.get(), pool.get()
    pool.put(first)
    pool.put(second)
    assert pool.get() is second
    assert pool.get() is first
    pool.put(first)
    pool.put(second)


def test_pool_surplus_connections_reach_max_idle(limited, clock):
    pool = limited(size=3, max_idle=100)
    raws = [pool.get() for _ in range(3)]
    for raw in raws:
        pool.put(raw)
    busy = raws[-1]
    for _ in range(3):
        clock.now += 40
        assert pool.get() is busy
        pool.put(busy)
    assert [is_closed(raw) for raw in raws] == [True, True, False]
    assert pool.checkedin == 1
    assert pool.checkedout == 0
    assert pool.overflow == -2


def test_pool_closes_idle_connections_on_return(limited, clock):
    pool = limited(size=2, max_idle=100)
    first, second = pool.get(), pool.get()
    pool.put(first)
    clock.now += 100
    pool.put(second)
    assert is_closed(first)
    assert not is_closed(second)
    assert pool.checkedin == 1


def test_pool_replaces_connections_after_a_quiet_period(limited, clock):
    pool = limited(size=2, overflow=0, timeout=0.01, max_idle=100)
    first, second = pool.get(), pool.get()
    pool.put(first)
    pool.put(second)
    clock.now += 100
    assert pool.checkedin == 2
    fresh = pool.get()
    assert fresh is not first
    assert fresh is not second
    assert is_closed(first)
    assert is_closed(second)
    assert pool.checkedin == 0
    assert pool.checkedout == 1
    pool.put(fresh)


def test_pool_timeout_defaults_to_30_seconds(monkeypatch):
    assert pool_module.DEFAULT_TIMEOUT == 30
    monkeypatch.setattr(pool_module, "DEFAULT_TIMEOUT", 0.01)
    pool = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}", size=1, overflow=0
    )
    raw = pool.get()
    with pytest.raises(exc.TimeoutError):
        pool.get()
    pool.put(raw)
    pool.close()


def test_pool_timeout_none_waits_for_a_connection(monkeypatch):
    monkeypatch.setattr(pool_module, "DEFAULT_TIMEOUT", 0.01)
    pool = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}",
        size=1,
        overflow=0,
        timeout=None,
        check_same_thread=False,
    )
    raw = pool.get()
    results = queue.Queue()
    waiter = threading.Thread(target=lambda: results.put(pool.get()))
    waiter.start()
    time.sleep(0.05)
    assert waiter.is_alive()
    pool.put(raw)
    waiter.join(5)
    assert results.get(timeout=1) is raw
    pool.put(raw)
    pool.close()


def test_pool_keeps_autocommit_until_a_checkout_needs_another_mode(limited):
    pool = limited(size=1)
    raw = pool.get(autocommit=True)
    pool.put(raw)
    assert pool.in_autocommit(raw)
    assert pool.get(autocommit=True) is raw
    assert pool.in_autocommit(raw)
    pool.put(raw)
    assert pool.get() is raw
    assert not pool.in_autocommit(raw)
    pool.put(raw)
    assert not pool.in_autocommit(raw)


@pytest.mark.parametrize("option", ["max_lifetime", "max_idle"])
@pytest.mark.parametrize("value", [0, -1])
def test_pool_rejects_limits_that_are_not_positive(option, value):
    with pytest.raises(ValueError, match=option):
        connect_pool(f"sqlite3+pool:///{util.SQLITE_FILE}", **{option: value})


def test_pool_limits_keep_slots_correct_across_threads():
    pool = connect_pool(
        f"sqlite3+pool:///{util.SQLITE_FILE}",
        size=2,
        overflow=2,
        timeout=10,
        max_lifetime=0.002,
        max_idle=0.001,
        check_same_thread=False,
    )
    errors = []

    def work():
        try:
            for _ in range(100):
                pool.put(pool.get())
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(30)
    assert not errors
    assert not any(thread.is_alive() for thread in threads)
    assert pool.checkedout == 0
    assert pool.checkedin <= 2
    pool.close()
    assert pool.checkedin == 0
    assert pool.checkedout == 0


@pytest.mark.postgres
def test_postgres_database_replaces_connection(pgdriver, clock):
    db = Database(pgdriver.pool_uri, max_lifetime=100)
    with db.cursor as cur:
        pid = cur.query("SELECT pg_backend_pid()").value()
    with db.cursor as cur:
        assert cur.query("SELECT pg_backend_pid()").value() == pid
    clock.now += 100
    with db.cursor as cur:
        assert cur.query("SELECT pg_backend_pid()").value() != pid
    db.close()


@pytest.mark.mysql
def test_mysql_database_replaces_connection(clock):
    db = Database(util.MYSQL_POOL_URI, max_idle=100)
    with db.cursor as cur:
        pid = cur.query("SELECT CONNECTION_ID()").value()
    with db.cursor as cur:
        assert cur.query("SELECT CONNECTION_ID()").value() == pid
    clock.now += 100
    with db.cursor as cur:
        assert cur.query("SELECT CONNECTION_ID()").value() != pid
    db.close()


def lost_connection(db, killer, pid_sql, kill_sql, error):
    with pytest.raises(error):
        with db.cursor as cur:
            cur.execute(pid_sql)
            killer.execute(kill_sql.format(pid=cur.fetchone()[0]))
            cur.execute("SELECT 1")
    with db.cursor as cur:
        cur.execute("SELECT 1")
        assert cur.fetchone()[0] == 1
    db.close()


@pytest.mark.postgres
@pytest.mark.parametrize("contextcommit", [False, True])
@pytest.mark.parametrize("pooled", [True, False])
def test_postgres_lost_connection(pgdriver, pooled, contextcommit):
    if pooled:
        db = Database(
            pgdriver.pool_uri,
            size=1,
            overflow=0,
            timeout=0.1,
            contextcommit=contextcommit,
        )
    else:
        db = Database(
            pgdriver.uri,
            persist=True,
            pessimistic=True,
            contextcommit=contextcommit,
        )
    lost_connection(
        db,
        Database(pgdriver.uri),
        "SELECT pg_backend_pid()",
        "SELECT pg_terminate_backend({pid}, 5000)",
        exc.ConnectionLost,
    )


@pytest.mark.mysql
@pytest.mark.parametrize("contextcommit", [False, True])
@pytest.mark.parametrize("pooled", [True, False])
def test_mysql_lost_connection(pooled, contextcommit):

    if pooled:
        db = Database(
            util.MYSQL_POOL_URI,
            size=1,
            overflow=0,
            timeout=0.1,
            contextcommit=contextcommit,
        )
    else:
        db = Database(
            util.MYSQL_URI,
            persist=True,
            pessimistic=True,
            contextcommit=contextcommit,
        )
    lost_connection(
        db,
        Database(util.MYSQL_URI),
        "SELECT CONNECTION_ID()",
        "KILL {pid}",
        exc.ConnectionLost,
    )


def finite_pool(uri):
    conn = connect(uri, size=1, overflow=4, timeout=0.05)
    conns = queue.Queue()
    exces = queue.Queue()

    def addconn(conns, conn):
        try:
            conns.put(conn.get())
        except exc.TimeoutError as e:
            assert str(e).startswith("QueuePool limit of size")
            exces.put(e)

    ts = []
    for _ in range(20):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        ts.append(t)
    for t in ts:
        t.join()

    # qsize returns the approximate size of the queue.
    # The result should be 15 but we can't be sure.
    assert exces.qsize() > 10

    while not conns.empty():
        c = conns.get()
        conn.put(c)
    conn.close()


@pytest.mark.postgres
def test_postgres_finite_pool(pgdriver):
    finite_pool(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_finite_pool():
    finite_pool(util.MYSQL_POOL_URI)


def infinite_pool(uri):
    conn = connect(uri, size=1, overflow=-1)
    conns = queue.Queue()

    def addconn(conns, conn):
        conns.put(conn.get())

    threads = []
    for _ in range(20):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    threads = []
    for _ in range(5):
        c = conns.get()
        conn.put(c)
    for _ in range(10):
        t = threading.Thread(target=addconn, args=(conns, conn))
        t.start()
        threads.append(t)
    for t in threads:
        t.join()
    assert conns.qsize() == 25

    while not conns.empty():
        c = conns.get()
        conn.put(c)
    conn.close()


@pytest.mark.postgres
def test_postgres_infinite_pool(pgdriver):
    infinite_pool(pgdriver.pool_uri)


@pytest.mark.mysql
def test_mysql_infinite_pool():
    infinite_pool(util.MYSQL_POOL_URI)


def persistent_pool(uri, sqldirs):
    with pytest.raises(ValueError) as e:
        Database(uri, sqldirs, persist=True)
    assert str(e.value).startswith("Persistent connections")


@pytest.mark.postgres
def test_postgres_persistent_pool(pgdriver, named_sqldirs):
    persistent_pool(pgdriver.pool_uri, named_sqldirs)


@pytest.mark.mysql
def test_mysql_persistent_pool(named_sqldirs):
    persistent_pool(util.MYSQL_POOL_URI, named_sqldirs)


def failing_check(uri, error):
    conn = connect_single(uri, pessimistic=True)
    connmock = Mock()
    connmock.cursor = get_cursor_mock(error)
    with pytest.raises(exc.ConnectionLost):
        conn._check(connmock)


@pytest.mark.postgres
def test_postgres_failing_check(pgdriver):
    failing_check(pgdriver.uri, pgdriver.dbapi.OperationalError)


@pytest.mark.mysql
def test_mysql_failing_check():
    import MySQLdb

    failing_check(util.MYSQL_URI, MySQLdb.OperationalError)


def test_sqlite_failing_connection():
    with pytest.raises(exc.ConnectionError):
        connect("sqlite3:/// \n//\r /").get()


@pytest.mark.mysql
def test_mysql_failing_connection():
    with pytest.raises(exc.ConnectionError):
        connect(
            "mysqlclient://wrong_user_n4me:wrong_p4$$wrd@/wrng_db_n4me"
        ).get()


@pytest.mark.postgres
def test_postgresql_failing_connection(pgdriver):
    with pytest.raises(exc.ConnectionError):
        connect(
            pgdriver.name + "://wrong_user_n4me:wrong_p4$$wrd@/wrng_db_n4me"
        ).get()
