from __future__ import annotations

import threading
import uuid
from typing import (
    TYPE_CHECKING,
    Any,
)

from . import exc
from .errors import (
    new_cursor,
    translating,
)
from .occupation import (
    check_idle,
    occupants,
)

if TYPE_CHECKING:
    from .conn import RawConnection
    from .cursor import BaseCursor

_lock = threading.Lock()
# The open blocks by id() of their connection. A block refers to its
# connection, so the id can't be reused while the block is listed.
_blocks: dict[int, list[Any]] = {}


def in_block(raw_conn: RawConnection) -> bool:
    return id(raw_conn) in _blocks


def check_no_block(raw_conn: RawConnection) -> None:
    if in_block(raw_conn):
        raise exc.APIError(
            "commit() and rollback() can't run in a transaction block. The "
            "block commits at its end and rolls back if an exception leaves "
            "it."
        )


def end_blocks(raw_conn: RawConnection) -> None:
    """The connection is being reset, which rolls back its transaction."""
    with _lock:
        for block in _blocks.pop(id(raw_conn), ()):
            block.ended = True


class BaseBlock:
    """A nestable transaction block: the outermost one on a connection owns
    the transaction, the ones inside it are savepoints."""

    def __init__(self, cursor: BaseCursor[Any]) -> None:
        self.cursor = cursor
        self.conn = cursor._conn()
        self.raw_conn = cursor._raw_conn()
        self.autocommit = translating(self.conn, self.conn.in_autocommit)(
            self.raw_conn
        )
        self.ended = False
        self.savepoint: str | None = None
        if in_block(self.raw_conn):
            self.savepoint = f"quma_{uuid.uuid4().hex}"
        elif translating(self.conn, self.conn.in_transaction)(self.raw_conn):
            raise exc.APIError(
                "A transaction is already open on this connection, so a "
                "transaction block can't own it. Even a SELECT can open one. "
                "Start the block before the first statement, commit first, "
                "or use autocommit."
            )

    @property
    def _driver_ends(self) -> bool:
        # psycopg2's commit() does nothing in autocommit, and without it a
        # COMMIT statement makes psycopg2 lose track of the transaction.
        return self.savepoint is None and not self.autocommit

    def _begin_statements(self) -> tuple[str, ...]:
        if self.savepoint:
            return (f"SAVEPOINT {self.savepoint}",)
        # Without autocommit psycopg2 and psycopg send BEGIN themselves, and
        # a second one logs a warning on the server. SQLite needs it, since
        # releasing a savepoint outside a transaction commits.
        if self.autocommit or self.conn.dialect != "postgresql":
            return ("BEGIN",)
        return ()

    def _commit_statements(self) -> tuple[str, ...]:
        if self.savepoint:
            return (f"RELEASE SAVEPOINT {self.savepoint}",)
        return ("COMMIT",) if self.autocommit else ()

    def _rollback_statements(self) -> tuple[str, ...]:
        if self.savepoint:
            return (
                f"ROLLBACK TO SAVEPOINT {self.savepoint}",
                f"RELEASE SAVEPOINT {self.savepoint}",
            )
        return ("ROLLBACK",) if self.autocommit else ()

    def _check_commit(self) -> None:
        if self.ended:
            raise exc.APIError(
                "The transaction was rolled back before the end of its "
                "block, because its connection was returned."
            )
        check_idle(self.raw_conn)
        if self.conn.in_failed_transaction(self.raw_conn):
            # COMMIT would silently roll back an aborted transaction.
            raise exc.APIError(
                "A statement in the transaction block failed, so PostgreSQL "
                "aborted the transaction and the block rolled back. Let the "
                "exception leave the block, or wrap the statement in a "
                "nested block."
            )

    def _driver(self, call: Any) -> Any:
        return translating(self.conn, call)

    def _blocking_streams(self) -> list[Any]:
        return [s for s in occupants(self.raw_conn) if s.blocks]

    def _register(self) -> None:
        with _lock:
            _blocks.setdefault(id(self.raw_conn), []).append(self)

    def forget(self) -> None:
        with _lock:
            listed = _blocks.get(id(self.raw_conn), [])
            if self in listed:
                listed.remove(self)
            if not listed:
                _blocks.pop(id(self.raw_conn), None)


class Block(BaseBlock):
    def begin(self) -> None:
        self._run(self._begin_statements())
        self._register()

    def commit(self) -> None:
        self._check_commit()
        self._run(self._commit_statements())
        if self._driver_ends:
            self._driver(self.raw_conn.commit)()

    def rollback(self) -> None:
        if self.ended:
            return
        for stream in self._blocking_streams():
            stream.close()
        self._run(self._rollback_statements())
        if self._driver_ends:
            self._driver(self.raw_conn.rollback)()

    def _run(self, statements: tuple[str, ...]) -> None:
        # A cursor of its own: the query's cursor may hold an unread result.
        for statement in statements:
            raw = new_cursor(self.conn, self.conn.cursor, self.raw_conn)
            try:
                self._driver(self.conn.get_cursor_attr(raw, "execute"))(
                    statement
                )
            finally:
                self._driver(raw.close)()
