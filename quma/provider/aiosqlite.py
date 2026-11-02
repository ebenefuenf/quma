try:
    import aiosqlite
except ImportError as e:
    raise ImportError(
        "In order to use quma with aiosqlite you need to install aiosqlite"
    ) from e

import asyncio
import sqlite3
from contextlib import suppress

from .. import (
    conn,
    errors,
    exc,
)
from ..rows import (
    ChangelingRow,
    Row,
)
from .sqlite3 import row_factory


class Cursor:
    """Creates aiosqlite's cursor on first use: it has to be awaited, and
    quma gets cursors from its other drivers without an await."""

    def __init__(self, conn):
        self.connection = conn
        self._cursor = None

    @property
    def description(self):
        return self._cursor.description if self._cursor else None

    @property
    def rowcount(self):
        return self._cursor.rowcount if self._cursor else -1

    @property
    def lastrowid(self):
        return self._cursor.lastrowid if self._cursor else None

    def __getattr__(self, name):
        return getattr(self._cursor, name)

    async def _run(self, method, *args):
        try:
            if self._cursor is None:
                self._cursor = await self.connection.cursor()
            return await getattr(self._cursor, method)(*args)
        except asyncio.CancelledError:
            # The statement would go on running in the connection's thread,
            # and aiosqlite's interrupt() would queue up behind it.
            with suppress(ValueError):
                self.connection._conn.interrupt()
            raise
        except ValueError as e:
            # aiosqlite's error for a closed connection, sqlite3's is this.
            raise sqlite3.ProgrammingError(str(e)) from e

    async def execute(self, sql, parameters=None):
        await self._run("execute", sql, parameters)
        return self

    async def executemany(self, sql, parameters):
        await self._run("executemany", sql, parameters)
        return self

    async def executescript(self, sql):
        await self._run("executescript", sql)
        return self

    async def fetchone(self):
        return await self._run("fetchone")

    async def fetchmany(self, size=None):
        rows = await self._run("fetchmany", size)
        return rows if self.description is not None else ()

    async def fetchall(self):
        rows = await self._run("fetchall")
        return rows if self.description is not None else ()

    async def close(self):
        if self._cursor is not None:
            await self._run("close")


class AsyncConnection(conn.AsyncConnection):
    dialect = "sqlite"
    driver_error = sqlite3.Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        if not self.database:
            raise ValueError("Required database path missing")
        self.has_rowcount = False

    def cursor(self, conn):
        return Cursor(conn)

    def stream_cursor(self, conn):
        return Cursor(conn)

    async def create_conn(self, **kwargs):
        # The event loop's thread sets isolation_level and reads the state,
        # while the connection's own thread is idle.
        kwargs["check_same_thread"] = False
        conn = aiosqlite.connect(self.database, **kwargs)
        # Otherwise a connection that wasn't closed keeps the process alive.
        conn._thread.daemon = True
        try:
            await conn
        except sqlite3.Error as e:
            raise errors.connection_error(e, self.dialect) from e
        conn.row_factory = row_factory(
            ChangelingRow if self.changeling else Row
        )
        return await self.disable_autocommit(conn)

    async def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.isolation_level = None
        return conn

    async def disable_autocommit(self, conn):
        conn.isolation_level = "DEFERRED"
        return conn

    def in_autocommit(self, conn):
        return conn.isolation_level is None

    def in_transaction(self, conn):
        return conn.in_transaction

    async def _check(self, conn):
        try:
            async with conn.execute("SELECT 1"):
                pass
        except (sqlite3.Error, ValueError) as e:
            raise exc.ConnectionLost(str(e)) from e
