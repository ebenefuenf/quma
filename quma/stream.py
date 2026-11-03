from __future__ import annotations

import operator
import threading
import uuid
from collections.abc import (
    Callable,
    Sequence,
)
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
)

from . import exc
from .errors import (
    new_cursor,
    translating,
)
from .hooks import observed

if TYPE_CHECKING:
    from .conn import (
        Params,
        RawConnection,
        Row,
    )
    from .query import BaseQuery

# The driver's default arraysize of 1 would cost a round trip per row.
SIZE = 2000

# libpq's PQTRANS_INTRANS, in psycopg2 and psycopg.
INTRANS = 2

CLOSED_EARLY = (
    "The stream was closed before its end, because its cursor was closed or "
    "its connection returned."
)

_lock = threading.Lock()
# The open streams by id() of their connection. A stream refers to its
# connection, so the id can't be reused while the stream is listed.
_streams: dict[int, list[Any]] = {}


def streams(raw_conn: RawConnection) -> list[Any]:
    with _lock:
        return list(_streams.get(id(raw_conn), ()))


def blocked(raw_conn: RawConnection) -> bool:
    if id(raw_conn) not in _streams:
        return False
    return any(stream.blocks for stream in streams(raw_conn))


def check_idle(raw_conn: RawConnection) -> None:
    if blocked(raw_conn):
        raise exc.APIError(
            "A stream or copy holds this connection, so it can't run other "
            "statements. Read the stream to its end or close it first. In "
            "async code, leaving the loop early doesn't close it: wrap it in "
            "contextlib.aclosing()."
        )


def _to_close(raw_conn: RawConnection, cursor: Any) -> list[Any]:
    found = [
        stream
        for stream in streams(raw_conn)
        if cursor is None or stream.cursor is cursor
    ]
    # What holds the connection comes first, the others need the connection.
    return sorted(found, key=lambda stream: not stream.blocks)


def close_streams(raw_conn: RawConnection, cursor: Any = None) -> None:
    """Close the streams on ``raw_conn``, or only those of ``cursor``."""
    for stream in _to_close(raw_conn, cursor):
        stream.close()


async def aclose_streams(raw_conn: RawConnection, cursor: Any = None) -> None:
    for stream in _to_close(raw_conn, cursor):
        await stream.close()


def _register(stream: Any) -> None:
    with _lock:
        _streams.setdefault(id(stream.raw_conn), []).append(stream)


def _unregister(stream: Any) -> None:
    with _lock:
        listed = _streams.get(id(stream.raw_conn), [])
        if stream in listed:
            listed.remove(stream)
        if not listed:
            _streams.pop(id(stream.raw_conn), None)


class BaseOccupation:
    """A stream or copy of the driver is running on a connection. psycopg holds
    the connection's lock until it ends, so anything else on the connection,
    a rollback too, would wait for it forever."""

    blocks = True

    def __init__(self, cursor: Any, finish: Callable[[], Any]) -> None:
        cursor._cursor()
        self.cursor = cursor
        self.raw_conn = cursor._raw_conn()
        self.finish = finish
        self.closed = False
        _register(self)

    def forget(self) -> bool:
        """Return False if it has ended already."""
        if self.closed:
            return False
        self.closed = True
        _unregister(self)
        return True


class Occupation(BaseOccupation):
    def close(self) -> None:
        if self.forget():
            # A lost connection can't finish it, and is discarded anyway.
            with suppress(Exception):
                self.finish()


class DriverIterator:
    """What psycopg's ``cursor.stream()`` returns. Only the iterator refers to
    this object, so dropping it ends the stream, as with the driver's own."""

    def __init__(self, use: Occupation, next_row: Callable[[], Any]) -> None:
        self.use = use
        self.next_row = next_row

    def __iter__(self) -> DriverIterator:
        return self

    def __next__(self) -> Any:
        if self.use.closed:
            raise exc.APIError(CLOSED_EARLY)
        try:
            return self.next_row()
        except BaseException:
            self.use.close()
            raise

    def close(self) -> None:
        self.use.close()

    def __del__(self) -> None:
        self.use.close()


class DriverContext:
    """What psycopg's ``cursor.copy()`` returns."""

    def __init__(self, cursor: Any, manager: Any) -> None:
        self.cursor = cursor
        self.manager = manager
        self.use: Occupation

    def __enter__(self) -> Any:
        self.use = Occupation(self.cursor, self._abort)
        enter = translating(self.cursor._conn(), self.manager.__enter__)
        try:
            return enter()
        except BaseException:
            self.use.forget()
            raise

    def __exit__(self, *exc_info: Any) -> Any:
        if self.use.forget():
            leave = translating(self.cursor._conn(), self.manager.__exit__)
            return leave(*exc_info)
        return False

    def _abort(self) -> None:
        # Only with an exception does psycopg stop the COPY, and without
        # ending it the next statement waits for its rest.
        error = exc.APIError(CLOSED_EARLY)
        self.manager.__exit__(type(error), error, None)


class BaseStream:
    """Reads the result of a query in batches, on a driver cursor of its
    own, without loading it whole: a server-side cursor on PostgreSQL,
    an unbuffered cursor on MySQL."""

    def __init__(self, query: BaseQuery, size: int) -> None:
        self.size = operator.index(size)
        if self.size < 1:
            raise ValueError("A stream needs a size of at least 1.")
        self.query = query
        self.cursor = query.cursor
        self.conn = self.cursor._conn()
        self.raw_conn = self.cursor._raw_conn()
        self.postgres = self.conn.dialect == "postgresql"
        # MySQL can't run other statements before the stream has ended.
        self.blocks = self.conn.dialect == "mysql"
        self.name = f"quma_{uuid.uuid4().hex}"
        self.raw: Any = None
        self.done = False
        self.description: Sequence[Sequence[Any]] | None = None
        if (
            self.postgres
            and self.raw_conn.autocommit
            and not self.conn.in_transaction(self.raw_conn)
        ):
            # Its cursor would end with the statement that declares it.
            raise exc.APIError(
                "PostgreSQL streams results in transactions only. Open the "
                "cursor without autocommit, or stream in a transaction block."
            )

    def _prepare(self) -> tuple[str, Params]:
        query = self.query
        content, params = query.script.prepare(
            self.cursor, list(query.args), query.kwargs, query.prepare_params
        )
        if self.postgres:
            content = f'DECLARE "{self.name}" NO SCROLL CURSOR FOR {content}'
        return content, params

    def _open(self) -> None:
        self.raw = new_cursor(
            self.conn, self.conn.stream_cursor, self.raw_conn
        )
        _register(self)

    def _forget(self) -> None:
        _unregister(self)

    def _send(self, content: str, params: Params) -> Any:
        return observed(
            self.cursor.db.on_execute,
            self.query.script.name,
            self._attr("execute"),
            (content, params),
            {},
        )

    def _batch(self) -> str:
        return f'FETCH FORWARD {self.size} FROM "{self.name}"'

    def _check_open(self) -> None:
        if self.raw is None:
            raise exc.APIError(CLOSED_EARLY)

    def _ended(self, rows: Sequence[Row]) -> bool:
        self.done = len(rows) < self.size
        return self.done

    def _attr(self, key: str) -> Any:
        return translating(
            self.conn,
            self.conn.get_cursor_attr(self.raw, key),
            self.query.script.name,
        )

    def mogrify(self, content: str, params: Params) -> str:
        return self.conn.mogrify(self.raw, content, params)


class Stream(BaseStream):
    def open(self) -> None:
        content, params = self._prepare()
        self._open()
        script = self.query.script
        try:
            self._send(content, params)
        finally:
            script.echo and script.mogrify(self, content, params)
        if not self.postgres:
            self.description = self.raw.description
            self.done = self.description is None

    def fetch(self) -> Sequence[Row]:
        if self.done:
            return ()
        self._check_open()
        if self.postgres:
            check_idle(self.raw_conn)
            self._attr("execute")(self._batch())
            rows = self._attr("fetchall")()
            self.description = self.raw.description
        else:
            rows = self._attr("fetchmany")(self.size)
        if self._ended(rows):
            self.close()
        return rows

    def close(self) -> None:
        raw, self.raw = self.raw, None
        if raw is None:
            return
        try:
            # The end of the transaction closes the server-side cursor, and
            # a MySQL connection that can't be read to the end is discarded.
            with suppress(Exception):
                if self.postgres and not blocked(self.raw_conn):
                    self._close_portal(raw)
                raw.close()
        finally:
            self._forget()

    def _close_portal(self, raw: Any) -> None:
        execute = self.conn.get_cursor_attr(raw, "execute")
        if not self.done:
            # A commit or rollback since the last batch has closed it, and
            # closing it again would fail and abort the transaction.
            if self.raw_conn.info.transaction_status != INTRANS:
                return
            execute(
                "SELECT 1 FROM pg_catalog.pg_cursors WHERE name = %s",
                [self.name],
            )
            if not self.conn.get_cursor_attr(raw, "fetchall")():
                return
        execute(f'CLOSE "{self.name}"')
