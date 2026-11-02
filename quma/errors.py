"""Turns the driver's exceptions into quma's.

The class comes from the server's error code. The driver's class only
decides if the code is unknown, because drivers disagree: a CHECK violation
is an ``OperationalError`` on MySQL, ``RAISE EXCEPTION`` an ``InternalError``
on psycopg2 and a ``ProgrammingError`` on psycopg.
"""

from __future__ import annotations

import gc
import re
from collections.abc import Awaitable, Callable
from typing import Any

from . import exc

_POSTGRESQL: dict[Any, type[exc.DatabaseError]] = {
    "08": exc.ConnectionLost,
    "22": exc.DataError,
    "23": exc.IntegrityError,
    "23502": exc.NotNullViolation,
    "23503": exc.ForeignKeyViolation,
    "23505": exc.UniqueViolation,
    "23514": exc.CheckViolation,
    "23P01": exc.ExclusionViolation,
    "25P03": exc.ConnectionLost,  # idle_in_transaction_session_timeout
    "25P04": exc.ConnectionLost,  # transaction_timeout
    "40001": exc.TransactionConflict,
    "40P01": exc.TransactionConflict,
    "42": exc.ProgrammingError,
    "55P03": exc.TransactionConflict,
    "57P01": exc.ConnectionLost,
    "57P02": exc.ConnectionLost,
    "57P03": exc.ConnectionLost,
    "57P05": exc.ConnectionLost,  # idle_session_timeout
    "P0001": exc.RaisedError,
}

_MYSQL: dict[Any, type[exc.DatabaseError]] = {
    1044: exc.ProgrammingError,  # no access to the database
    1048: exc.NotNullViolation,
    1053: exc.ConnectionLost,  # server shutdown
    1054: exc.ProgrammingError,  # missing column
    1062: exc.UniqueViolation,
    1142: exc.ProgrammingError,  # no permission on the table
    1143: exc.ProgrammingError,  # no permission on the column
    1205: exc.TransactionConflict,  # lock wait timeout
    1213: exc.TransactionConflict,  # deadlock
    1216: exc.ForeignKeyViolation,
    1217: exc.ForeignKeyViolation,
    1227: exc.ProgrammingError,  # missing privilege
    1264: exc.DataError,  # out of range
    1265: exc.DataError,  # truncated
    1292: exc.DataError,  # incorrect value
    1305: exc.ProgrammingError,  # missing routine or savepoint
    1364: exc.NotNullViolation,  # no value and no default
    1365: exc.DataError,  # division by zero
    1366: exc.DataError,  # incorrect value
    1370: exc.ProgrammingError,  # no permission on the routine
    1406: exc.DataError,  # too long
    1451: exc.ForeignKeyViolation,
    1452: exc.ForeignKeyViolation,
    1586: exc.UniqueViolation,
    1644: exc.RaisedError,  # SIGNAL
    1690: exc.DataError,  # out of range
    1927: exc.ConnectionLost,  # killed, MariaDB
    2006: exc.ConnectionLost,  # server has gone away
    2013: exc.ConnectionLost,  # lost during the query
    2055: exc.ConnectionLost,
    3572: exc.TransactionConflict,  # NOWAIT, MySQL
    3819: exc.CheckViolation,  # MySQL
    4025: exc.CheckViolation,  # MariaDB
    4031: exc.ConnectionLost,  # wait_timeout, MySQL
}

_SQLITE: dict[Any, type[exc.DatabaseError]] = {
    "SQLITE_BUSY": exc.TransactionConflict,
    "SQLITE_CONSTRAINT": exc.IntegrityError,
    "SQLITE_CONSTRAINT_CHECK": exc.CheckViolation,
    "SQLITE_CONSTRAINT_FOREIGNKEY": exc.ForeignKeyViolation,
    "SQLITE_CONSTRAINT_NOTNULL": exc.NotNullViolation,
    "SQLITE_CONSTRAINT_PRIMARYKEY": exc.UniqueViolation,
    "SQLITE_CONSTRAINT_ROWID": exc.UniqueViolation,
    "SQLITE_CONSTRAINT_TRIGGER": exc.RaisedError,
    "SQLITE_CONSTRAINT_UNIQUE": exc.UniqueViolation,
    "SQLITE_ERROR": exc.ProgrammingError,
    "SQLITE_LOCKED": exc.TransactionConflict,
    "SQLITE_MISMATCH": exc.DataError,
    "SQLITE_TOOBIG": exc.DataError,
}

_CODES = {"postgresql": _POSTGRESQL, "mysql": _MYSQL, "sqlite": _SQLITE}

# The driver's classes that mean the same on every driver, for unknown codes
# and for errors the driver raises itself.
_CATEGORIES = {
    "DataError": exc.DataError,
    "IntegrityError": exc.IntegrityError,
    "ProgrammingError": exc.ProgrammingError,
}

# What drivers raise for a value they can't send: text their charset can't
# hold, or too large an integer. psycopg2 raises a plain ValueError for NUL.
_VALUE_ERRORS = (ValueError, OverflowError)

_MYSQL_LAST_QUOTED = re.compile(r"'([^']*)'\Z")
_MYSQL_CONSTRAINT = re.compile(r"CONSTRAINT `((?:[^`]|``)*)`")
_MYSQL_CHECK = re.compile(r"'([^']*)' is violated")


def _bad_value(error: Exception) -> bool:
    # Other ValueErrors may be about the SQL, like a bad format character.
    return isinstance(error, (UnicodeError, OverflowError)) or (
        "NUL" in str(error)
    )


def translate(
    error: Exception, dialect: str, script: str | None = None
) -> exc.DatabaseError:
    code = _code(error, dialect)
    return _class(error, dialect, code)(
        _message(error, dialect),
        code=code,
        constraint=_constraint(error, dialect, code),
        script=script,
    )


def connection_error(error: Exception, dialect: str) -> exc.ConnectionError:
    return exc.ConnectionError(
        _message(error, dialect), code=_code(error, dialect)
    )


def translating(
    conn: Any, call: Callable[..., Any], script: str | None = None
) -> Callable[..., Any]:
    """Return ``call``, which calls the driver, raising quma's exceptions.
    If it returns an awaitable, the result raises them once awaited."""

    def run(*args: Any, **kwargs: Any) -> Any:
        try:
            result = call(*args, **kwargs)
        except conn.driver_error as e:
            raise conn.translate(e, script) from e
        except _VALUE_ERRORS as e:
            if _bad_value(e):
                raise exc.DataError(str(e), script=script) from e
            raise
        # inspect.isawaitable() would cost more than the rest of this.
        if hasattr(type(result), "__await__"):
            return _awaited(conn, result, script)
        return result

    return run


def new_cursor(conn: Any, create: Callable[..., Any], raw_conn: Any) -> Any:
    """Return the cursor ``create`` makes. Not through :func:`translating`:
    asyncmy's cursors are awaitable, and must stay cursors."""
    try:
        return create(raw_conn)
    except conn.driver_error as e:
        raise conn.translate(e) from e


async def _awaited(
    conn: Any, result: Awaitable[Any], script: str | None
) -> Any:
    try:
        return await result
    except conn.driver_error as e:
        raise conn.translate(e, script) from e
    except _VALUE_ERRORS as e:
        if _bad_value(e):
            raise exc.DataError(str(e), script=script) from e
        raise


def _code(error: Exception, dialect: str) -> Any:
    if dialect == "postgresql":
        # psycopg and psycopg2. Without one, the error isn't the server's.
        return getattr(error, "sqlstate", None) or getattr(
            error, "pgcode", None
        )
    if dialect == "mysql":
        # Errors the driver raises itself have only a message.
        code = error.args[0] if error.args else None
        return code if isinstance(code, int) else None
    return getattr(error, "sqlite_errorname", None)


def _family(code: Any, dialect: str) -> Any:
    if dialect == "postgresql" and code:
        return code[:2]
    if dialect == "sqlite" and code:
        return "_".join(code.split("_")[:2])
    return None


def _class(
    error: Exception, dialect: str, code: Any
) -> type[exc.DatabaseError]:
    codes = _CODES[dialect]
    found = codes.get(code) or codes.get(_family(code, dialect))
    if found:
        return found
    names = [base.__name__ for base in type(error).__mro__]
    # Both drivers report a connection that broke without a server's code.
    if dialect == "postgresql" and not code and "OperationalError" in names:
        return exc.ConnectionLost
    if "InterfaceError" in names and _not_connected(error, dialect, code):
        return exc.ConnectionLost
    for name in names:
        if name in _CATEGORIES:
            return _CATEGORIES[name]
    return exc.DatabaseError


def _not_connected(error: Exception, dialect: str, code: Any) -> bool:
    # psycopg2's "cursor already closed" stays: it can't tell a lost connection
    # from a cursor that was closed on a working one.
    if dialect == "postgresql":
        return str(error) == "connection already closed"
    return dialect == "mysql" and code == 0


def _message(error: Exception, dialect: str) -> str:
    if dialect == "mysql" and len(error.args) > 1:
        # mysqlclient leaves a NULL in args if the server's message isn't UTF-8,
        # like a duplicate key on charset latin1, and reading it crashes Python.
        if len(gc.get_referents(error.args)) < len(error.args):
            code = error.args[0]
            error.args = (
                code,
                f"Error {code}, its message isn't valid UTF-8.",
            )
        return str(error.args[1])
    return str(error).strip()


def _constraint(error: Exception, dialect: str, code: Any) -> str | None:
    if dialect == "postgresql":
        diag = getattr(error, "diag", None)
        return getattr(diag, "constraint_name", None)
    if dialect == "mysql":
        return _mysql_constraint(_message(error, dialect), code)
    # SQLite names columns or an expression instead.
    return None


def _mysql_constraint(message: str, code: Any) -> str | None:
    if code in (1062, 1586):
        # Last, because the message quotes the duplicate value before it.
        match = _MYSQL_LAST_QUOTED.search(message)
        return match[1].rsplit(".", 1)[-1] if match else None
    if code in (1216, 1217, 1451, 1452, 4025):
        match = _MYSQL_CONSTRAINT.search(message)
        return match[1].replace("``", "`") if match else None
    if code == 3819:
        match = _MYSQL_CHECK.search(message)
        return match[1] if match else None
    return None
