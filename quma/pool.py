# Portions of this module have been copied and modified from SQLAlchemy's
# pool module and is copyrighted by Michael Bayer under the terms of the
# MIT license. https://www.sqlalchemy.org/

from __future__ import annotations

import threading
from collections import deque
from math import inf
from random import uniform
from time import monotonic
from typing import Any
from urllib.parse import ParseResult

from . import exc
from .conn import (
    Connection,
    Params,
    RawConnection,
    RawCursor,
)


class Connections:
    """The connections a pool has open, and which of them are idle."""

    def __init__(
        self, max_lifetime: float | None, max_idle: float | None
    ) -> None:
        for name, limit in (
            ("max_lifetime", max_lifetime),
            ("max_idle", max_idle),
        ):
            if limit is not None and limit <= 0:
                raise ValueError(f"{name} must be greater than 0")
        self._max_lifetime = max_lifetime
        self._max_idle = max_idle
        self._deadlines: dict[int, float] = {}
        # Ordered by the time of return, the oldest first.
        self._idle: deque[tuple[RawConnection, float]] = deque()

    @property
    def open(self) -> int:
        return len(self._deadlines)

    @property
    def idle(self) -> int:
        return len(self._idle)

    def add(self, conn: RawConnection) -> None:
        deadline = inf
        if self._max_lifetime is not None:
            # Connections opened together must not all expire together.
            deadline = monotonic() + self._max_lifetime * uniform(0.95, 1)
        self._deadlines[id(conn)] = deadline

    def remove(self, conn: RawConnection) -> None:
        self._deadlines.pop(id(conn), None)

    def returned(self, conn: RawConnection) -> None:
        self._idle.append((conn, monotonic()))

    def take(self) -> RawConnection | None:
        if not self._idle:
            return None
        # Reusing the most recent one lets the surplus reach max_idle. In the
        # order of return, every connection keeps being used.
        lifo = self._max_idle is not None
        return self._idle.pop()[0] if lifo else self._idle.popleft()[0]

    def pop_expired(self) -> RawConnection | None:
        """Stop tracking and return an idle connection past a limit."""
        if self._max_lifetime is None and self._max_idle is None:
            return None
        now = monotonic()
        max_idle = inf if self._max_idle is None else self._max_idle
        for i, (conn, returned) in enumerate(self._idle):
            deadline = self._deadlines.get(id(conn), inf)
            if now - returned >= max_idle or now >= deadline:
                del self._idle[i]
                self.remove(conn)
                return conn
        return None


class Pool:
    """A pool of connections"""

    def __init__(
        self, conn_class: type[Connection], url: ParseResult, **kwargs: Any
    ) -> None:
        self._size: int = kwargs.pop("size", 5)
        self._max_overflow: int = kwargs.pop("overflow", 10)
        self._timeout: float | None = kwargs.pop("timeout", None)
        self._pessimistic = kwargs.get("pessimistic", False)
        self._conns = Connections(
            kwargs.pop("max_lifetime", None), kwargs.pop("max_idle", None)
        )
        # A semaphore, not a full queue, limits the connections: a waiting
        # thread also wakes when a broken connection was discarded.
        self._slots = (
            None
            if self._max_overflow == -1
            else threading.Semaphore(self._size + self._max_overflow)
        )
        self._lock = threading.Lock()
        self._closed = False
        self._conn = conn_class(url, **kwargs)
        if self._conn.persist:
            raise ValueError("Persistent connections are not allowed")

    def get(self, autocommit: bool = False) -> RawConnection:
        self._acquire()
        try:
            return self._checkout(autocommit)
        except BaseException:
            self._release()
            raise

    def put(self, conn: RawConnection) -> None:
        # Always rollback possibly open transaction so that as the
        # connection is set up to be used again, it’s in a “clean”
        # state with no references held to the previous series of
        # operations.
        try:
            # Switching costs a round trip on MySQL, so a connection keeps
            # its mode until a checkout needs another one.
            reusable = self._conn.reset(conn, keep_autocommit=True)
        except BaseException:
            self._drop(conn)
            self._release()
            raise
        with self._lock:
            keep = (
                reusable and not self._closed and self._conns.idle < self._size
            )
            if keep:
                self._conns.returned(conn)
            else:
                self._conns.remove(conn)
        self._release()
        if reusable and not keep:
            self._conn.discard(conn)
        self._discard_expired()

    def close(self) -> None:
        idle = []
        with self._lock:
            self._closed = True
            while (conn := self._conns.take()) is not None:
                self._conns.remove(conn)
                idle.append(conn)
        for conn in idle:
            self._conn.discard(conn)

    def _acquire(self) -> None:
        if self._slots is None:
            return
        if not self._slots.acquire(timeout=self._timeout):
            raise exc.TimeoutError(
                f"QueuePool limit of size {self._size} overflow "
                f"{self._max_overflow} reached, connection timed out, "
                f"timeout {self._timeout}"
            )

    def _release(self) -> None:
        if self._slots is not None:
            self._slots.release()

    def _discard_expired(self) -> None:
        while True:
            with self._lock:
                conn = self._conns.pop_expired()
            if conn is None:
                return
            self._conn.discard(conn)

    def _checkout(self, autocommit: bool) -> RawConnection:
        self._discard_expired()
        with self._lock:
            conn = self._conns.take()
        if conn is None:
            return self._new(autocommit)
        try:
            if self._pessimistic:
                self._conn.check(conn)
            return self._conn.set_autocommit(autocommit, conn)
        except exc.ConnectionLost:
            self._drop(conn)
            return self._new(autocommit)
        except BaseException:
            self._drop(conn)
            raise

    def _new(self, autocommit: bool) -> RawConnection:
        conn = self._conn.get(autocommit=autocommit)
        with self._lock:
            self._conns.add(conn)
        return conn

    def _drop(self, conn: RawConnection) -> None:
        with self._lock:
            self._conns.remove(conn)
        self._conn.discard(conn)

    @property
    def driver_error(self) -> type[Exception]:
        return self._conn.driver_error

    def translate(
        self, error: Exception, script: str | None = None
    ) -> exc.DatabaseError:
        return self._conn.translate(error, script)

    def cursor(self, conn: RawConnection) -> RawCursor:
        return conn.cursor()

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

    def mogrify(self, cursor: RawCursor, content: str, params: Params) -> str:
        return self._conn.mogrify(cursor, content, params)
