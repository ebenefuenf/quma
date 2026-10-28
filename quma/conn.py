from __future__ import annotations

from contextlib import suppress
from typing import (
    Any,
    Protocol,
    TypeVar,
)
from urllib.parse import ParseResult

from . import exc

# DB-API connections, cursors and rows differ from driver to driver.
RawConnection = Any
RawCursor = Any
Row = Any
Params = dict[str, Any] | list[Any]


class BaseConnectionLike(Protocol):
    """The part of the connection interface that does no I/O, shared by
    :class:`ConnectionLike` and :class:`AsyncConnectionLike`."""

    @property
    def has_rowcount(self) -> bool: ...

    def cursor(self, conn: RawConnection) -> RawCursor: ...

    def get_cursor_attr(self, cursor: RawCursor, key: str) -> Any: ...

    def mogrify(
        self, cursor: RawCursor, content: str, params: Params
    ) -> str: ...


class ConnectionLike(BaseConnectionLike, Protocol):
    """The interface :class:`quma.Database` uses to get connections:
    implemented by the provider connections and the connection pool."""

    def get(self, autocommit: bool = False) -> RawConnection: ...

    def put(self, conn: RawConnection) -> None: ...

    def close(self) -> None: ...


class AsyncConnectionLike(BaseConnectionLike, Protocol):
    """The interface :class:`quma.AsyncDatabase` uses to get connections:
    implemented by the async provider connections and the async pool."""

    async def open(self) -> None: ...

    async def get(self, autocommit: bool = False) -> RawConnection: ...

    async def put(self, conn: RawConnection) -> None: ...

    async def close(self) -> None: ...


ConnT = TypeVar("ConnT", bound=BaseConnectionLike)


class Connection:
    """Abstract base class for DBMS specific connection objects"""

    conn: RawConnection

    def __init__(self, url: ParseResult, kwargs: dict[str, Any]) -> None:
        # kwargs are the **kwargs passed to the specific provider
        # sub class. They must be passed as regular dict to be
        # able to pop some values which should not be passed
        # to the dbapi driver.
        self.database = url.path[1:]  # remove the leading slash
        self.username = url.username
        self.password = url.password
        self.url = url
        self.factory: Any = None
        self.changeling: bool = kwargs.pop("changeling", False)
        self.persist: bool = kwargs.pop("persist", False)
        self.pessimistic: bool = kwargs.pop("pessimistic", False)
        self.has_rowcount = True
        self.dbapi_kwargs = kwargs

    def _init_conn(self) -> None:
        if self.persist:
            self.conn = self.create_conn(**self.dbapi_kwargs)

    def cursor(self, conn: RawConnection) -> RawCursor:
        return conn.cursor()

    def get_cursor_attr(self, cursor: RawCursor, key: str) -> Any:
        return getattr(cursor, key)

    def create_conn(self, **kwargs: Any) -> RawConnection:
        raise NotImplementedError

    def enable_autocommit_if(
        self, autocommit: bool, conn: RawConnection
    ) -> RawConnection:
        raise NotImplementedError

    def disable_autocommit(self, conn: RawConnection) -> RawConnection:
        raise NotImplementedError

    def mogrify(self, cursor: RawCursor, content: str, params: Params) -> str:
        return content

    def get(self, autocommit: bool = False) -> RawConnection:
        if self.persist:
            if self.pessimistic:
                try:
                    self.check()
                except exc.OperationalError:
                    self.discard(self.conn)
                    self.conn = self.create_conn(**self.dbapi_kwargs)
            return self.enable_autocommit_if(autocommit, self.conn)
        return self.enable_autocommit_if(
            autocommit, self.create_conn(**self.dbapi_kwargs)
        )

    def reset(self, conn: RawConnection) -> bool:
        """Return False if ``conn`` is broken and has been discarded."""
        try:
            conn.rollback()
            self.disable_autocommit(conn)
        except Exception:
            # Closing ends the transaction too. Raising would hide the
            # error that broke the connection.
            self.discard(conn)
            return False
        return True

    def put(self, conn: RawConnection) -> None:
        if self.reset(conn) and not self.persist:
            conn.close()

    def close(self, conn: RawConnection | None = None) -> None:
        if conn:
            conn.close()
            return
        if getattr(self, "conn", None):
            self.conn.close()
            del self.conn

    def discard(self, conn: RawConnection) -> None:
        # Closing a broken connection can fail, MySQLdb raises if it is
        # already closed. That must not prevent replacing it.
        with suppress(Exception):
            conn.close()

    def _check(self, conn: RawConnection) -> None:
        raise NotImplementedError

    def check(self, conn: RawConnection | None = None) -> None:
        if conn:
            self._check(conn)
            return
        self._check(self.conn)
