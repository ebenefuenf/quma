"""Every way we know to open, close, lose and misuse a connection, on every
driver and connection type, with the same steps for sync and async, so a fix
made on one side only fails here. Whatever a step raises must be quma's own
error. Afterwards the pool must have its slots back and the database must work
again. A sync deadlock can't be interrupted, so each scenario gets a thread.

It runs on SQLite only, unless QUMA_LIFECYCLE_MATRIX=full, which is for changes
to how cursors and connections open, close or recover. That takes about three
minutes, and QUMA_MYSQL_PORT=3307 -m mysql repeats it on MariaDB.
"""

import asyncio
import inspect
import os
import threading
import time
from contextlib import suppress
from typing import Any

import pytest

from .. import AsyncDatabase, Database
from . import util
from .test_aio_lifecycle import lose as alose
from .test_lifecycle import lose

FULL = os.environ.get("QUMA_LIFECYCLE_MATRIX") == "full"
STEP_TIMEOUT = 3.0
SCENARIO_TIMEOUT = 25.0

SQL = "SELECT 1 AS a"
ROWS = (
    "WITH RECURSIVE t(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM t "
    "WHERE n < 500) SELECT n FROM t"
)
COPY = "COPY (SELECT 1) TO STDOUT"

# The name in the test id: the URL's scheme, and whether it's async.
TARGETS = {
    "sqlite3": ("sqlite3", False),
    "aiosqlite": ("aiosqlite", True),
    "psycopg2": ("psycopg2", False),
    "psycopg": ("psycopg", False),
    "psycopg-async": ("psycopg", True),
    "mysqlclient": ("mysqlclient", False),
    "asyncmy": ("asyncmy", True),
}
MODULES = {"mysqlclient": "MySQLdb"}
MARKS = {
    "psycopg2": pytest.mark.postgres,
    "psycopg": pytest.mark.postgres,
    "mysqlclient": pytest.mark.mysql,
    "asyncmy": pytest.mark.mysql,
}
CONNECTIONS: dict[str, tuple[str, dict[str, Any]]] = {
    "plain": ("", {}),
    "persist": ("", {"persist": True}),
    "persist+pessimistic": ("", {"persist": True, "pessimistic": True}),
    "pool": ("+pool", {"size": 1, "overflow": 0, "timeout": 1}),
    "pool+overflow": ("+pool", {"size": 1, "overflow": 1, "timeout": 1}),
    "pool+pessimistic": (
        "+pool",
        {"size": 1, "overflow": 0, "timeout": 1, "pessimistic": True},
    ),
}

USE = {
    "with+with": "with with all exit exit",
    "call+with+with": "call with with exit exit",
    "call+call": "call call close",
    "create+create": "create create close",
    "with+create": "with create exit",
    "with+call": "with call exit",
    "reopen": "with all exit with all exit",
    "close+close": "create close close",
    "put+put": "create put put",
    "close+with": "create close with all exit",
    "after:all": "with exit all",
    "after:commit": "with exit commit",
    "after:rollback": "with exit rollback",
    "after:execute": "with exit execute",
    "after:fetchall": "with execute exit fetchall",
    "after:description": "with execute exit description",
    "after:transaction": "with exit tx_enter",
    "after:stream": "with exit stream next",
    "after:mogrify": "with exit mogrify",
    "never:all": "new all",
    "never:commit": "new commit",
    "never:execute": "new execute",
    "never:transaction": "new tx_enter",
    "never:close": "new close",
    "never:put": "new put",
    "never:exit": "new exit",
    "carrier:with+with": "carrier with with all exit exit release",
    "carrier:reopen": "carrier with all exit with all exit release",
    "carrier:commit-after": "carrier with all exit commit release",
    "carrier:all-after": "carrier with all exit all release",
    "carrier:close+with": "carrier with close with all exit release",
    "carrier:release+all": "carrier with release all",
    "carrier:release+with": "carrier with exit release with all exit release",
    "dbclose+with": "dbclose with",
    "dbclose-before-with": "new dbclose with all exit",
    "dbclose-before-call": "new dbclose call all close",
    "dbexecute": "dbexecute dbexecute",
    "dbclose-open": "create dbclose all close",
    "dbclose-open-exit": "with dbclose exit",
    "transaction:close-inside": "with tx_enter close tx_exit exit",
    "transaction:commit-inside": "with tx_enter commit tx_exit exit",
    "transaction:left-open": "with tx_enter exit",
}
STREAMS = {
    "stream:exit": "with stream next exit",
    "stream:resume": "with stream next exit next",
    "stream:query": "with stream next all next exit",
    "stream:commit": "with stream next commit next exit",
    "stream:transaction": "with stream next tx_enter tx_exit exit",
    "stream:close": "create stream next close",
    "stream:release": "carrier with stream next release",
    "stream:dbclose": "create stream next dbclose",
    "stream:unstarted": "with stream exit",
    "stream:second": "with stream next stream next exit",
}
LOST = {
    "lost:all+all": "with kill all all exit",
    "lost:value": "with kill value exit",
    "lost:one": "with kill one exit",
    "lost:execute+execute": "with kill execute execute exit",
    "lost:many": "with kill many exit",
    "lost:many-size": "with kill many_size exit",
    "lost:fetchall": "with execute kill fetchall exit",
    "lost:stream": "with kill stream next exit",
    "lost:stream-middle": "with stream next kill next next next exit",
    "lost:commit": "with execute kill commit exit",
    "lost:commit-idle": "with kill commit exit",
    "lost:rollback": "with execute kill rollback exit",
    "lost:rollback-idle": "with kill rollback exit",
    "lost:exit": "with execute kill exit",
    "lost:exit-idle": "with kill exit",
    "lost:close": "create execute kill close",
    "lost:transaction": "with kill tx_enter all tx_exit exit",
    "lost:failed-then-transaction": "with kill all tx_enter exit",
    "lost:in-transaction": "with tx_enter kill all tx_exit exit",
    "lost:transaction-end": "with tx_enter execute kill tx_exit exit",
    "lost:mogrify": "with kill mogrify exit",
    "lost:between": "with keep_raw exit kill with all exit",
    "lost:between+dbclose": "with keep_raw exit kill dbclose",
    "lost:open+dbclose": "with kill dbclose",
    "lost:failed+dbclose": "with kill all exit dbclose",
    "lost:carrier": "carrier with kill all exit release",
    "lost:carrier-next": "carrier with kill all exit with all exit release",
    "lost:carrier-commit": "carrier with execute kill exit commit release",
    "lost:autocommit-next": "with keep_raw exit kill autocommit all exit",
    "lost:autocommit-open": "autocommit kill all all close",
    "lost:dbexecute": "with keep_raw exit kill dbexecute dbexecute",
    "closed:with": "with raw_close all exit",
    "closed:between": "with keep_raw exit raw_close with all exit",
    "closed:autocommit": "with keep_raw exit raw_close autocommit all exit",
    "closed:transaction": "with raw_close tx_enter all tx_exit exit",
}
# psycopg holds its connection's lock during its own stream() and copy().
PSYCOPG = {
    "driver-stream:exit": "with driver_stream next exit",
    "driver-stream:query": "with driver_stream next all exit",
    "driver-stream:commit": "with driver_stream next commit exit",
    "driver-stream:transaction": (
        "with driver_stream next tx_enter tx_exit exit"
    ),
    "driver-stream:close": "create driver_stream next close",
    "driver-stream:resume": "with driver_stream next exit next",
    "driver-stream:unstarted": "with driver_stream exit",
    "driver-stream:unstarted-resume": "with driver_stream exit next",
    "driver-stream:release": "carrier with driver_stream next release",
    "driver-stream:dbclose": "create driver_stream next dbclose",
    "driver-stream:closed": (
        "with driver_stream next stream_close rollback all exit"
    ),
    "driver-stream:dropped": (
        "with driver_stream next drop_stream rollback all exit"
    ),
    "driver-stream:second": "with driver_stream next driver_stream next exit",
    "copy:close": "with copy_enter close copy_exit exit",
    "copy:query": "with copy_enter all copy_exit exit",
    "copy:commit": "with copy_enter commit copy_exit exit",
    "copy:exit": "with copy_enter exit",
    "copy:release": "carrier with copy_enter release",
    "copy:dbclose": "create copy_enter dbclose",
}
# Their only job is to break the connection, which may already be gone.
BREAKING = {"kill", "raw_close"}


class Run:
    """One scenario's objects. A step returns what async code has to await."""

    def __init__(self, is_async: bool) -> None:
        self.is_async = is_async
        self.now = "start"
        self.db: Any = None
        self.cur: Any = None
        self.raw: Any = None
        self.iterator: Any = None
        self.copy: Any = None
        self.block: Any = None
        self.owner = object()

    def enter(self, manager: Any) -> Any:
        if self.is_async:
            return manager.__aenter__()
        return manager.__enter__()

    def exit(self, manager: Any) -> Any:
        if self.is_async:
            return manager.__aexit__(None, None, None)
        return manager.__exit__(None, None, None)

    def _opened(self) -> Any:
        if self.cur is None:
            self.cur = self.db.cursor
        return self.cur

    def _raw(self) -> Any:
        if self.cur is not None and self.cur.raw_conn is not None:
            return self.cur.raw_conn
        return self.raw

    def step_new(self) -> None:
        self.cur = self.db.cursor

    def step_with(self) -> Any:
        return self.enter(self._opened())

    def step_exit(self) -> Any:
        return self.exit(self.cur)

    def step_call(self) -> Any:
        return self._opened()()

    def step_autocommit(self) -> Any:
        self.cur = self.db.cursor
        return self.cur(autocommit=True)

    def step_create(self) -> Any:
        return self._opened().create_cursor()

    def step_close(self) -> Any:
        return self.cur.close()

    def step_put(self) -> Any:
        return self.cur.put()

    def step_all(self) -> Any:
        return self.cur.query(SQL).all()

    def step_value(self) -> Any:
        return self.cur.query(SQL).value()

    def step_one(self) -> Any:
        return self.cur.query(SQL).one()

    def step_many(self) -> Any:
        return self.cur.query(SQL).many().get()

    def step_many_size(self) -> Any:
        return self.cur.query(SQL).many().get(1)

    def step_execute(self) -> Any:
        return self.cur.execute(SQL)

    def step_fetchall(self) -> Any:
        return self.cur.fetchall()

    def step_description(self) -> Any:
        return self.cur.description

    def step_commit(self) -> Any:
        return self.cur.commit()

    def step_rollback(self) -> Any:
        return self.cur.rollback()

    def step_mogrify(self) -> Any:
        return self.cur.mogrify(SQL, {})

    def step_tx_enter(self) -> Any:
        self.block = self.cur.transaction()
        return self.enter(self.block)

    def step_tx_exit(self) -> Any:
        return self.exit(self.block)

    def step_carrier(self) -> None:
        self.cur = self.db(self.owner).cursor

    def step_release(self) -> Any:
        return self.db.release(self.owner)

    def step_dbclose(self) -> Any:
        return self.db.close()

    def step_dbexecute(self) -> Any:
        return self.db.execute(SQL)

    def step_keep_raw(self) -> None:
        self.raw = self.cur.raw_conn

    def step_kill(self) -> Any:
        return alose(self._raw()) if self.is_async else lose(self._raw())

    def step_raw_close(self) -> Any:
        return self._raw().close()

    def step_stream(self) -> None:
        rows = self.cur.query(ROWS).stream(size=2)
        self.iterator = rows.__aiter__() if self.is_async else iter(rows)

    def step_driver_stream(self) -> None:
        self.iterator = self.cur.stream(ROWS)

    def step_next(self) -> Any:
        if self.is_async:
            return self.iterator.__anext__()
        return next(self.iterator)

    def step_stream_close(self) -> Any:
        if self.is_async:
            return self.iterator.aclose()
        return self.iterator.close()

    def step_drop_stream(self) -> None:
        self.iterator = None
        time.sleep(0.01)

    def step_copy_enter(self) -> Any:
        self.copy = self.cur.copy(COPY)
        return self.enter(self.copy)

    def step_copy_exit(self) -> Any:
        return self.exit(self.copy)


async def finish(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await asyncio.wait_for(value, STEP_TIMEOUT)
    return value


def is_quma_error(error: BaseException) -> bool:
    return type(error).__module__.startswith("quma")


async def play(run: Run, steps: str, problems: list[str]) -> None:
    for name in steps.split():
        run.now = name
        try:
            await finish(getattr(run, f"step_{name}")())
        except (StopIteration, StopAsyncIteration):
            pass
        except BaseException as error:
            if name not in BREAKING and not is_quma_error(error):
                problems.append(f"{name} raised {error!r}")


async def clean_up(run: Run, problems: list[str]) -> None:
    run.now = "clean up"
    try:
        if run.cur is not None:
            await finish(run.cur.close())
        await finish(run.db.release(run.owner))
    except BaseException as error:
        problems.append(f"cleaning up raised {error!r}")


async def works_again(run: Run, problems: list[str]) -> None:
    run.now = "recovery"
    errors = []
    # The first cursor may be the one to find the connection lost.
    for _ in range(2):
        cur = run.db.cursor
        try:
            await finish(run.enter(cur))
            value = await finish(cur.query(SQL).value())
            await finish(run.exit(cur))
            if value == 1:
                return
        except BaseException as error:
            errors.append(error)
            with suppress(BaseException):
                await finish(cur.close())
    problems.append(f"didn't recover: {errors!r}")


async def scenario(
    run: Run,
    uri: str,
    options: dict[str, Any],
    steps: str,
    problems: list[str],
) -> None:
    run.db = (AsyncDatabase if run.is_async else Database)(uri, **options)
    await play(run, steps, problems)
    await clean_up(run, problems)
    if run.db.conn is not None:
        stats = run.db.pool_stats()
        if stats is not None and stats.in_use:
            problems.append(f"lost {stats.in_use} of the pool's slots")
        await works_again(run, problems)
    run.now = "closing"
    try:
        await finish(run.db.close())
    except BaseException as error:
        problems.append(f"closing the database raised {error!r}")


def in_thread(is_async: bool, *args: Any) -> list[str]:
    problems: list[str] = []
    run = Run(is_async)

    def target() -> None:
        try:
            asyncio.run(scenario(run, *args, problems))
        except BaseException as error:
            problems.append(f"{run.now} raised {error!r}")

    thread = threading.Thread(target=target, daemon=True)
    thread.start()
    thread.join(SCENARIO_TIMEOUT)
    if thread.is_alive():
        problems.append(f"hung in {run.now}")
    return problems


def uri(scheme: str, suffix: str, tmp_path: Any) -> str:
    if scheme in ("sqlite3", "aiosqlite"):
        base = f"{scheme}:///{tmp_path / 'lifecycle.sqlite'}"
    elif scheme in ("psycopg2", "psycopg"):
        base = util.pg_uri(scheme)
    else:
        base = util.MYSQL_URI.replace("mysqlclient://", f"{scheme}://")
    return base.replace("://", f"{suffix}://", 1)


def cases() -> Any:
    targets = TARGETS if FULL else ("sqlite3", "aiosqlite")
    connections = CONNECTIONS if FULL else ("plain", "pool")
    for target in targets:
        scheme = TARGETS[target][0]
        scenarios = USE | STREAMS | LOST
        if scheme == "psycopg":
            scenarios |= PSYCOPG
        mark = MARKS.get(scheme)
        for connection in connections:
            for name, steps in scenarios.items():
                yield pytest.param(
                    target,
                    connection,
                    steps,
                    id=f"{target}-{connection}-{name}",
                    marks=() if mark is None else mark,
                )


@pytest.mark.parametrize(("target", "connection", "steps"), list(cases()))
def test_scenario(target, connection, steps, tmp_path):
    scheme, is_async = TARGETS[target]
    pytest.importorskip(MODULES.get(scheme, scheme))
    suffix, options = CONNECTIONS[connection]
    problems = in_thread(
        is_async, uri(scheme, suffix, tmp_path), options, steps
    )
    assert not problems
