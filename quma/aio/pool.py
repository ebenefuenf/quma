from __future__ import annotations

import asyncio
from typing import Any
from urllib.parse import ParseResult

from .. import exc
from ..conn import (
    AsyncConnection,
    Params,
    RawConnection,
    RawCursor,
)
from ..pool import (
    DEFAULT_TIMEOUT,
    Connections,
    max_waiting,
)


class AsyncPool:
    """A pool of async connections with the options of :class:`quma.pool.Pool`."""

    def __init__(
        self,
        conn_class: type[AsyncConnection],
        url: ParseResult,
        **kwargs: Any,
    ) -> None:
        self._size: int = kwargs.pop("size", 5)
        self._max_overflow: int = kwargs.pop("overflow", 10)
        self._timeout: float | None = kwargs.pop("timeout", DEFAULT_TIMEOUT)
        self._max_waiting = max_waiting(kwargs, self._max_overflow)
        self._waiting = 0
        self._pessimistic = kwargs.get("pessimistic", False)
        self._conns = Connections(
            kwargs.pop("max_lifetime", None), kwargs.pop("max_idle", None)
        )
        # A semaphore, not a full queue, limits the connections: a waiting
        # task also wakes when a broken connection was discarded.
        self._slots = (
            None
            if self._max_overflow == -1
            else asyncio.Semaphore(self._size + self._max_overflow)
        )
        self._closed = False
        self._conn = conn_class(url, **kwargs)
        if self._conn.persist:
            raise ValueError("Persistent connections are not allowed")

    async def open(self) -> None:
        await self.put(await self.get())

    async def get(self, autocommit: bool = False) -> RawConnection:
        await self._acquire()
        try:
            return await self._checkout(autocommit)
        except BaseException:
            self._release()
            raise

    async def put(self, conn: RawConnection) -> None:
        try:
            # Switching costs a round trip on MySQL, so a connection keeps
            # its mode until a checkout needs another one.
            reusable = await self._conn.reset(conn, keep_autocommit=True)
        except BaseException:
            # A cancelled reset has discarded the connection.
            self._conns.remove(conn)
            self._release()
            raise
        keep = reusable and not self._closed and self._conns.idle < self._size
        if keep:
            self._conns.returned(conn)
        else:
            self._conns.remove(conn)
        self._release()
        if reusable and not keep:
            await self._conn.discard(conn)
        await self._discard_expired()

    async def close(self) -> None:
        self._closed = True
        while (conn := self._conns.take()) is not None:
            self._conns.remove(conn)
            await self._conn.discard(conn)

    async def _acquire(self) -> None:
        if self._slots is None:
            return
        if not self._slots.locked():
            # A timeout would set and cancel a timer on every checkout.
            await self._slots.acquire()
            return
        if self._max_waiting is not None:
            if self._waiting >= self._max_waiting:
                raise exc.TooManyWaiting(
                    f"Pool limit of size {self._size} overflow "
                    f"{self._max_overflow} reached, {self._waiting} waiting, "
                    f"max_waiting {self._max_waiting}"
                )
        self._waiting += 1
        try:
            async with asyncio.timeout(self._timeout):
                await self._slots.acquire()
        except TimeoutError as e:
            raise exc.TimeoutError(
                f"Pool limit of size {self._size} overflow {self._max_overflow} "
                f"reached, connection timed out, timeout {self._timeout}"
            ) from e
        finally:
            self._waiting -= 1

    def _release(self) -> None:
        if self._slots is not None:
            self._slots.release()

    async def _discard_expired(self) -> None:
        while (conn := self._conns.pop_expired()) is not None:
            await self._conn.discard(conn)

    async def _checkout(self, autocommit: bool) -> RawConnection:
        await self._discard_expired()
        conn = self._conns.take()
        if conn is None:
            return await self._new(autocommit)
        try:
            if self._pessimistic:
                await self._conn.check(conn)
            return await self._conn.set_autocommit(autocommit, conn)
        except exc.ConnectionLost:
            await self._drop(conn)
            return await self._new(autocommit)
        except BaseException:
            await self._drop(conn)
            raise

    async def _new(self, autocommit: bool) -> RawConnection:
        conn = await self._conn.get(autocommit=autocommit)
        self._conns.add(conn)
        return conn

    async def _drop(self, conn: RawConnection) -> None:
        self._conns.remove(conn)
        await self._conn.discard(conn)

    @property
    def driver_error(self) -> type[Exception]:
        return self._conn.driver_error

    def translate(
        self, error: Exception, script: str | None = None
    ) -> exc.DatabaseError:
        return self._conn.translate(error, script)

    def cursor(self, conn: RawConnection) -> RawCursor:
        return self._conn.cursor(conn)

    def stream_cursor(self, conn: RawConnection) -> RawCursor:
        return self._conn.stream_cursor(conn)

    def get_cursor_attr(self, cursor: RawCursor, key: str) -> Any:
        return self._conn.get_cursor_attr(cursor, key)

    def in_autocommit(self, conn: RawConnection) -> bool:
        return self._conn.in_autocommit(conn)

    def in_transaction(self, conn: RawConnection) -> bool:
        return self._conn.in_transaction(conn)

    def in_failed_transaction(self, conn: RawConnection) -> bool:
        return self._conn.in_failed_transaction(conn)

    def mogrify(self, cursor: RawCursor, content: str, params: Params) -> str:
        return self._conn.mogrify(cursor, content, params)

    @property
    def has_rowcount(self) -> bool:
        return self._conn.has_rowcount

    @property
    def dialect(self) -> str:
        return self._conn.dialect

    def status(self) -> str:
        return (
            f"Pool size: {self.size} Connections in pool: {self.checkedin} "
            f"Current Overflow: {self.overflow} Current Checked out "
            f"connections: {self.checkedout}"
        )

    @property
    def size(self) -> int:
        return self._size

    @property
    def checkedin(self) -> int:
        return self._conns.idle

    @property
    def overflow(self) -> int:
        return self._conns.open - self._size

    @property
    def checkedout(self) -> int:
        return self._conns.open - self._conns.idle
