from __future__ import annotations

import asyncio
from dataclasses import replace
from time import monotonic

from .. import exc
from ..conn import (
    AsyncConnection,
    RawConnection,
)
from ..pool import (
    BasePool,
    PoolStats,
)


class AsyncPool(BasePool[AsyncConnection]):
    """A pool of async connections with the options of :class:`quma.pool.Pool`."""

    _semaphore = asyncio.Semaphore

    async def open(self) -> None:
        await self.put(await self.get())

    async def get(self, autocommit: bool = False) -> RawConnection:
        await self._acquire()
        try:
            conn = await self._checkout(autocommit)
        except BaseException:
            self._release()
            raise
        self._stats.checkouts += 1
        return conn

    async def put(self, conn: RawConnection) -> None:
        try:
            # Switching costs a round trip on MySQL, so a connection keeps
            # its mode until a checkout needs another one.
            reusable = await self._conn.reset(conn, keep_autocommit=True)
        except BaseException:
            # A cancelled reset has discarded the connection.
            self._conns.remove(conn)
            self._stats.closed_broken += 1
            self._release()
            raise
        keep = reusable and not self._closed and self._conns.idle < self._size
        if keep:
            self._conns.returned(conn)
        else:
            self._conns.remove(conn)
            if not reusable:
                self._stats.closed_broken += 1
            elif self._closed:
                self._stats.closed_shutdown += 1
            else:
                self._stats.closed_surplus += 1
        self._release()
        if reusable and not keep:
            await self._conn.discard(conn)
        await self._discard_expired()

    async def close(self) -> None:
        self._closed = True
        while (conn := self._conns.take()) is not None:
            self._conns.remove(conn)
            self._stats.closed_shutdown += 1
            await self._conn.discard(conn)

    async def _acquire(self) -> None:
        if self._slots is None:
            return
        if not self._slots.locked():
            # A timeout would set and cancel a timer on every checkout.
            await self._slots.acquire()
            return
        if self._max_waiting is not None:
            if self._stats.waiting >= self._max_waiting:
                self._stats.rejected += 1
                raise exc.TooManyWaiting(
                    f"Pool limit of size {self._size} overflow "
                    f"{self._max_overflow} reached, {self._stats.waiting} "
                    f"waiting, max_waiting {self._max_waiting}"
                )
        self._stats.waiting += 1
        self._stats.waits += 1
        start = monotonic()
        try:
            async with asyncio.timeout(self._timeout):
                await self._slots.acquire()
        except TimeoutError as e:
            self._stats.timeouts += 1
            raise exc.TimeoutError(
                f"Pool limit of size {self._size} overflow {self._max_overflow} "
                f"reached, connection timed out, timeout {self._timeout}"
            ) from e
        finally:
            self._stats.waiting -= 1
            self._stats.wait_time += monotonic() - start

    async def _discard_expired(self) -> None:
        while (conn := self._conns.pop_expired()) is not None:
            self._stats.closed_expired += 1
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
        try:
            conn = await self._conn.get(autocommit=autocommit)
        except Exception:
            self._stats.connect_errors += 1
            raise
        self._conns.add(conn)
        self._stats.opened += 1
        return conn

    async def _drop(self, conn: RawConnection) -> None:
        self._conns.remove(conn)
        self._stats.closed_broken += 1
        await self._conn.discard(conn)

    def stats(self) -> PoolStats:
        return replace(
            self._stats, open=self._conns.open, idle=self._conns.idle
        )
