from __future__ import annotations

import operator
import uuid
from collections.abc import Sequence
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
from .occupation import (
    CLOSED_EARLY,
    blocked,
    check_idle,
    register,
    unregister,
)

if TYPE_CHECKING:
    from .conn import (
        Params,
        Row,
    )
    from .query import BaseQuery

# The driver's default arraysize of 1 would cost a round trip per row.
SIZE = 2000

# libpq's PQTRANS_INTRANS, in psycopg2 and psycopg.
INTRANS = 2


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
        self.raw_conn = self.cursor._idle_raw_conn()
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
        register(self)

    def _forget(self) -> None:
        unregister(self)

    def _send(self, content: str, params: Params) -> Any:
        return observed(
            self.cursor.db.on_execute,
            self.query.script.name,
            self._attr("execute", statement=True),
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

    def _attr(self, key: str, statement: bool = False) -> Any:
        return translating(
            self.conn,
            self.conn.get_cursor_attr(self.raw, key),
            self.query.script.name,
            statement,
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
