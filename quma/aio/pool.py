from __future__ import annotations

import asyncio
from collections import deque
from typing import Any
from urllib.parse import ParseResult

from .. import exc
from ..conn import (
    AsyncConnection,
    Params,
    RawConnection,
    RawCursor,
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
        self._timeout: float | None = kwargs.pop("timeout", None)
        self._pessimistic = kwargs.get("pessimistic", False)
        # A semaphore, not a full queue, limits the connections: a waiting
        # task also wakes when a broken connection was discarded.
        self._slots = (
            None
            if self._max_overflow == -1
            else asyncio.Semaphore(self._size + self._max_overflow)
        )
        self._idle: deque[RawConnection] = deque()
        self._opened = 0
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
            reusable = await self._conn.reset(conn)
        except BaseException:
            # A cancelled reset has discarded the connection.
            self._opened -= 1
            self._release()
            raise
        if reusable and not self._closed and len(self._idle) < self._size:
            self._idle.append(conn)
            self._release()
            return
        self._opened -= 1
        self._release()
        if reusable:
            await self._conn.discard(conn)

    async def close(self) -> None:
        self._closed = True
        while self._idle:
            conn = self._idle.popleft()
            self._opened -= 1
            await self._conn.discard(conn)

    async def _acquire(self) -> None:
        if self._slots is None:
            return
        try:
            async with asyncio.timeout(self._timeout):
                await self._slots.acquire()
        except TimeoutError as e:
            raise exc.TimeoutError(
                f"Pool limit of size {self._size} overflow {self._max_overflow} "
                f"reached, connection timed out, timeout {self._timeout}"
            ) from e

    def _release(self) -> None:
        if self._slots is not None:
            self._slots.release()

    async def _checkout(self, autocommit: bool) -> RawConnection:
        if not self._idle:
            return await self._new(autocommit)
        conn = self._idle.popleft()
        try:
            if self._pessimistic:
                await self._conn.check(conn)
            return await self._conn.enable_autocommit_if(autocommit, conn)
        except exc.OperationalError:
            await self._drop(conn)
            return await self._new(autocommit)
        except BaseException:
            await self._drop(conn)
            raise

    async def _new(self, autocommit: bool) -> RawConnection:
        conn = await self._conn.get(autocommit=autocommit)
        self._opened += 1
        return conn

    async def _drop(self, conn: RawConnection) -> None:
        self._opened -= 1
        await self._conn.discard(conn)

    def cursor(self, conn: RawConnection) -> RawCursor:
        return self._conn.cursor(conn)

    def get_cursor_attr(self, cursor: RawCursor, key: str) -> Any:
        return self._conn.get_cursor_attr(cursor, key)

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
        return len(self._idle)

    @property
    def overflow(self) -> int:
        return self._opened - self._size

    @property
    def checkedout(self) -> int:
        return self._opened - len(self._idle)
