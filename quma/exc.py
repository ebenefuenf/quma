from collections.abc import Sequence


class APIError(Exception):
    pass


class MultipleRowsError(Exception):
    pass


class DoesNotExistError(Exception):
    pass


class TimeoutError(Exception):
    """Raised when a connection pool times out on getting a connection."""


class TooManyWaiting(TimeoutError):
    """Raised at once when ``max_waiting`` requests already wait for a
    connection."""


class DatabaseError(Exception):
    """Anything the database or the driver reports. See
    :doc:`Handling errors <errors>`.

    :param message: The message of the database or the driver.
    :param code: The code of the database: an SQLSTATE like ``'23505'`` on
        PostgreSQL, an error number like ``1062`` on MySQL and MariaDB, a
        name like ``'SQLITE_CONSTRAINT_UNIQUE'`` on SQLite. ``None`` if the
        error has none.
    :param constraint: The name of the violated constraint, or ``None`` if
        it isn't known.
    :param script: The name of the script that failed, like ``users/add``,
        or ``None`` if the statement doesn't come from a script file.
    """

    def __init__(
        self,
        message: object = "",
        *,
        code: str | int | None = None,
        constraint: str | None = None,
        script: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.constraint = constraint
        self.script = script


class IntegrityError(DatabaseError):
    """A statement violated a constraint."""


class UniqueViolation(IntegrityError):
    """A unique or primary key constraint was violated."""


class ForeignKeyViolation(IntegrityError):
    """A foreign key constraint was violated."""


class NotNullViolation(IntegrityError):
    """A column that can't be empty was left empty."""


class CheckViolation(IntegrityError):
    """A check constraint was violated."""


class ExclusionViolation(IntegrityError):
    """An exclusion constraint was violated (PostgreSQL)."""


class DataError(DatabaseError):
    """A value doesn't fit: too long, out of range or of the wrong type."""


class ProgrammingError(DatabaseError):
    """The statement can't run: a syntax error, a missing table or column,
    a missing permission, a parameter that is missing or doesn't fit its
    placeholder."""


class MissingParameter(ProgrammingError, KeyError):
    """A placeholder has no value. Also a :class:`KeyError`, which is what
    psycopg2, mysqlclient and asyncmy raise for this, so code that catches it
    keeps working."""

    __str__ = Exception.__str__


class RaisedError(DatabaseError):
    """SQL raised the error itself: ``RAISE EXCEPTION`` on PostgreSQL,
    ``SIGNAL`` on MySQL and MariaDB, ``RAISE()`` on SQLite."""


class TransactionConflict(DatabaseError):
    """Another transaction got in the way: a deadlock, a serialization
    failure or a lock that wasn't free in time. Roll back and try the
    transaction again."""


class ConnectionError(DatabaseError):
    """The connection to the database can't be opened."""


class ConnectionLost(ConnectionError):
    """The connection to the database broke."""


class PlaceholderError(Exception):
    """Raised when a script contains driver placeholders where quma
    expects ``:name`` placeholders."""


class MappingError(Exception):
    """Raised when the rows of a query cannot be mapped to a target."""


class MissingColumnError(MappingError):
    """Raised when a column the mapping target requires is missing."""

    def __init__(self, columns: Sequence[str], target: type) -> None:
        self.columns = tuple(columns)
        self.target = target
        names = ", ".join(f'"{column}"' for column in self.columns)
        plural = "s" if len(self.columns) > 1 else ""
        super().__init__(
            f"Missing column{plural} {names} for {target.__qualname__}"
        )
