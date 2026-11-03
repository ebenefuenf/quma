"""What runs on a connection and has to end before the connection can do
anything else or go back: quma's streams, and psycopg's own stream and copy."""

from __future__ import annotations

import threading
from collections.abc import Callable
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
)

from . import exc
from .errors import translating

if TYPE_CHECKING:
    from .conn import RawConnection

CLOSED_EARLY = (
    "The stream was closed before its end, because its cursor was closed or "
    "its connection returned."
)

_lock = threading.Lock()
# What runs on a connection, by its id(). Each of them refers to the connection,
# so the id can't be reused while it's listed.
_occupants: dict[int, list[Any]] = {}


def occupants(raw_conn: RawConnection) -> list[Any]:
    with _lock:
        return list(_occupants.get(id(raw_conn), ()))


def blocked(raw_conn: RawConnection) -> bool:
    if id(raw_conn) not in _occupants:
        return False
    return any(occupant.blocks for occupant in occupants(raw_conn))


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
        occupant
        for occupant in occupants(raw_conn)
        if cursor is None or occupant.cursor is cursor
    ]
    # What holds the connection comes first, the others need the connection.
    return sorted(found, key=lambda occupant: not occupant.blocks)


def close_occupants(raw_conn: RawConnection, cursor: Any = None) -> None:
    """End what runs on ``raw_conn``, or only what ``cursor`` started."""
    for occupant in _to_close(raw_conn, cursor):
        occupant.close()


async def aclose_occupants(
    raw_conn: RawConnection, cursor: Any = None
) -> None:
    for occupant in _to_close(raw_conn, cursor):
        await occupant.close()


def register(occupant: Any) -> None:
    with _lock:
        _occupants.setdefault(id(occupant.raw_conn), []).append(occupant)


def unregister(occupant: Any) -> None:
    with _lock:
        listed = _occupants.get(id(occupant.raw_conn), [])
        if occupant in listed:
            listed.remove(occupant)
        if not listed:
            _occupants.pop(id(occupant.raw_conn), None)


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
        register(self)

    def forget(self) -> bool:
        """Return False if it has ended already."""
        if self.closed:
            return False
        self.closed = True
        unregister(self)
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
