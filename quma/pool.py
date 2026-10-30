# Portions of this module have been copied and modified from SQLAlchemy's
# pool module and is copyrighted by Michael Bayer under the terms of the
# MIT license. https://www.sqlalchemy.org/

from __future__ import annotations

import threading
from collections import deque
from typing import Any
from urllib.parse import ParseResult

from .conn import (
    Connection,
    Params,
    RawConnection,
    RawCursor,
)
from .exc import (
    OperationalError,
    TimeoutError,
)


class Pool:
    """A pool of connections"""

    def __init__(
        self, conn_class: type[Connection], url: ParseResult, **kwargs: Any
    ) -> None:
        self._size: int = kwargs.pop("size", 5)
        self._max_overflow: int = kwargs.pop("overflow", 10)
        self._timeout: float | None = kwargs.pop("timeout", None)
        self._pessimistic = kwargs.get("pessimistic", False)
        # A semaphore, not a full queue, limits the connections: a waiting
        # thread also wakes when a broken connection was discarded.
        self._slots = (
            None
            if self._max_overflow == -1
            else threading.Semaphore(self._size + self._max_overflow)
        )
        self._lock = threading.Lock()
        self._idle: deque[RawConnection] = deque()
        self._opened = 0
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
            reusable = self._conn.reset(conn)
        except BaseException:
            self._drop(conn)
            self._release()
            raise
        with self._lock:
            keep = (
                reusable and not self._closed and len(self._idle) < self._size
            )
            if keep:
                self._idle.append(conn)
            else:
                self._opened -= 1
        self._release()
        if reusable and not keep:
            self._conn.discard(conn)

    def close(self) -> None:
        with self._lock:
            self._closed = True
            idle, self._idle = self._idle, deque()
            self._opened -= len(idle)
        for conn in idle:
            self._conn.discard(conn)

    def _acquire(self) -> None:
        if self._slots is None:
            return
        if not self._slots.acquire(timeout=self._timeout):
            raise TimeoutError(
                f"QueuePool limit of size {self._size} overflow "
                f"{self._max_overflow} reached, connection timed out, "
                f"timeout {self._timeout}"
            )

    def _release(self) -> None:
        if self._slots is not None:
            self._slots.release()

    def _checkout(self, autocommit: bool) -> RawConnection:
        with self._lock:
            conn = self._idle.popleft() if self._idle else None
        if conn is None:
            return self._new(autocommit)
        try:
            if self._pessimistic:
                self._conn.check(conn)
            return self._conn.enable_autocommit_if(autocommit, conn)
        except OperationalError:
            self._drop(conn)
            return self._new(autocommit)
        except BaseException:
            self._drop(conn)
            raise

    def _new(self, autocommit: bool) -> RawConnection:
        conn = self._conn.get(autocommit=autocommit)
        with self._lock:
            self._opened += 1
        return conn

    def _drop(self, conn: RawConnection) -> None:
        with self._lock:
            self._opened -= 1
        self._conn.discard(conn)

    def cursor(self, conn: RawConnection) -> RawCursor:
        return conn.cursor()

    def get_cursor_attr(self, cursor: RawCursor, key: str) -> Any:
        return self._conn.get_cursor_attr(cursor, key)

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

    def mogrify(self, cursor: RawCursor, content: str, params: Params) -> str:
        return self._conn.mogrify(cursor, content, params)
