from __future__ import annotations

import inspect
from collections.abc import (
    Generator,
    Sequence,
)
from contextlib import (
    contextmanager,
    suppress,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Generic,
    Self,
)

from . import exc
from .conn import (
    BaseConnectionLike,
    ConnectionLike,
    ConnT,
    Params,
    RawConnection,
    RawCursor,
)
from .errors import (
    new_cursor,
    translating,
)
from .hooks import (
    OnExecute,
    observed,
)
from .namespace import (
    CursorNamespace,
    Namespace,
    get_namespace,
)
from .occupation import (
    DriverContext,
    DriverIterator,
    Occupation,
    blocked,
    check_idle,
    close_occupants,
)
from .query import (
    BaseQuery,
    Query,
)
from .script import (
    PrepareParams,
    Script,
)
from .transaction import (
    Block,
    check_no_block,
    in_block,
)

if TYPE_CHECKING:
    from .database import (
        BaseDatabase,
        Carrier,
    )

# The driver's cursor methods, which can't work without an open cursor.
DBAPI_CALLS = frozenset(
    (
        "callproc",
        "execute",
        "executemany",
        "fetchall",
        "fetchmany",
        "fetchone",
        "nextset",
        "scroll",
    )
)
# Read from the driver's cursor before SQL directories and scripts of that name,
# by quma too. Anything else comes after them, so the same SQL directory means the
# same on every driver, whatever else its cursor has.
DRIVER_ATTRS = DBAPI_CALLS | frozenset(
    (
        "arraysize",
        "connection",
        "cursor",
        "description",
        "executions",
        "has_rowcount",
        "lastrowid",
        "messages",
        "rowcount",
        "rownumber",
    )
)


class CarriedConnection(Generic[ConnT]):
    def __init__(self, conn: ConnT, raw_conn: RawConnection) -> None:
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper:
    def __init__(
        self,
        conn: BaseConnectionLike,
        raw_conn: RawConnection,
        raw_cursor: RawCursor,
        on_execute: OnExecute | None = None,
    ) -> None:
        self.conn = conn
        self.raw_conn = raw_conn
        self.cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount
        self._on_execute = on_execute
        # Tells a query whether the cursor still holds its result.
        self.executions = 0
        # What an error while fetching belongs to.
        self._script: str | None = None

    def execute(self, *args: Any, **kwargs: Any) -> Any:
        return self._run("execute", args, kwargs)

    def executemany(self, *args: Any, **kwargs: Any) -> Any:
        return self._run("executemany", args, kwargs)

    def callproc(self, *args: Any, **kwargs: Any) -> Any:
        return self._run("callproc", args, kwargs)

    def _run_script(
        self, script: str | None, content: str, params: Params
    ) -> Any:
        return self._run("execute", (content, params), {}, script)

    def _run(
        self, name: str, args: Any, kwargs: Any, script: str | None = None
    ) -> Any:
        check_idle(self.raw_conn)
        self.executions += 1
        self._script = script
        call = translating(
            self.conn,
            self.conn.get_cursor_attr(self.cursor, name),
            script,
            statement=True,
        )
        return observed(
            self._on_execute, script, call, args, kwargs, self._rowcount
        )

    def _rowcount(self) -> int | None:
        rowcount = self.conn.get_cursor_attr(self.cursor, "rowcount")
        return None if rowcount < 0 else rowcount

    def __getattr__(self, key: str) -> Any:
        value = self.conn.get_cursor_attr(self.cursor, key)
        if callable(value) and not isinstance(value, type):
            return translating(self.conn, value, self._script)
        return value


class BaseCursor(Generic[ConnT]):
    def __init__(
        self,
        db: BaseDatabase[ConnT],
        namespaces: dict[str, Namespace],
        contextcommit: bool,
        carrier: Carrier | None = None,
        autocommit: bool = False,
    ) -> None:
        self.db = db
        self.conn = db.conn
        self.namespaces = namespaces
        self.carrier = carrier
        self.autocommit = db.autocommit or (
            isinstance(autocommit, bool) and autocommit
        )
        self.raw_conn: RawConnection | None = None
        self.raw_cursor: RawCursorWrapper | None = None
        self.contextcommit = contextcommit
        self._opened_by_call = False
        self._open = False

    def _autocommit(self, autocommit: bool) -> bool:
        if isinstance(autocommit, bool) and autocommit:
            return True
        return self.autocommit

    def _carried_raw_conn(self) -> RawConnection | None:
        if self.carrier and self.carrier.conn:
            return self.carrier.conn.raw_conn
        return None

    def _attach(self, conn: ConnT, raw_conn: RawConnection) -> None:
        raw_cursor = new_cursor(conn, conn.cursor, raw_conn)
        if self.carrier and self.carrier.ended:
            # Released while this cursor opened: the connection is its own.
            self.carrier = None
        if self.carrier:
            if not self.carrier.conn:
                self.carrier.add_conn(CarriedConnection(conn, raw_conn))
            self.carrier.cursors.add(self)
        self.raw_conn = raw_conn
        self.raw_cursor = RawCursorWrapper(
            conn, raw_conn, raw_cursor, self.db.on_execute
        )

    def _detach(self, force: bool) -> tuple[ConnT, RawConnection] | None:
        """Return the connection to put back, or None if there is none."""
        if self.carrier and self.carrier.conn:
            if not force:
                return None
            carried = self.carrier.end()
            detached = (
                None if carried is None else (carried.conn, carried.raw_conn)
            )
        else:
            detached = (self._conn(), self.raw_conn)
        self.raw_conn = None
        self._opened_by_call = False
        return detached

    def _lose_carried(self) -> None:
        self.carrier = None
        self.raw_conn = None
        self._opened_by_call = False
        self._open = False

    def _cursor(self) -> RawCursorWrapper:
        # A carried cursor keeps raw_conn after put(), to commit later.
        if not self._open or self.raw_cursor is None:
            raise exc.APIError("The cursor has no open connection.")
        return self.raw_cursor

    def _conn(self) -> ConnT:
        if self.conn is None:
            raise exc.APIError("The database is closed.")
        return self.conn

    def _idle_raw_conn(self) -> RawConnection:
        if self.raw_conn is None:
            raise exc.APIError("The cursor has no open connection.")
        check_idle(self.raw_conn)
        return self.raw_conn

    def _commit_conn(self) -> RawConnection:
        raw_conn = self._idle_raw_conn()
        check_no_block(raw_conn)
        return raw_conn

    def _end_transaction(self, method: str) -> Any:
        raw_conn = self._commit_conn()
        return translating(self._conn(), getattr(raw_conn, method))()

    def _context_ends_transaction(self) -> bool:
        # A carried cursor inside another cursor's block leaves it to the block.
        return self.contextcommit and not in_block(self.raw_conn)

    def _driver_attr(self, value: Any) -> Any:
        return value

    def _query(
        self,
        script: Script,
        args: Sequence[Any],
        kwargs: dict[str, Any],
        prepare_params: PrepareParams | None,
    ) -> BaseQuery:
        raise NotImplementedError

    def _script(self, content: str, is_template: bool) -> Script:
        return Script(
            content,
            self.db.echo,
            is_template,
            self.db.sqldirs,
            self.db.prepare_params,
        )

    def get_conn_attr(self, attr: str) -> Any:
        return getattr(self.raw_conn, attr)

    def set_conn_attr(self, attr: str, value: Any) -> None:
        setattr(self.raw_conn, attr, value)

    def mogrify(self, content: str, params: Params) -> str:
        return self._conn().mogrify(self._cursor(), content, params)

    def __getattr__(self, attr: str) -> Any:
        if attr in DBAPI_CALLS:
            return self._driver_attr(getattr(self._cursor(), attr))
        if attr not in DRIVER_ATTRS:
            try:
                return CursorNamespace(get_namespace(self, attr), self)
            except AttributeError:
                pass
        try:
            value = getattr(self.raw_cursor, attr)
        except AttributeError as e:
            raise AttributeError(
                "Namespace, Root method, or cursor "
                f'attribute "{attr}" not found.'
            ) from e
        return self._driver_attr(value)


class Cursor(BaseCursor[ConnectionLike]):
    def __enter__(self) -> Self:
        # `with db.cursor() as cur` uses the connection opened by the call.
        if self._opened_by_call:
            self._opened_by_call = False
            return self
        return self.create_cursor()

    def __exit__(
        self, exc_type: type[BaseException] | None, *args: object
    ) -> None:
        if self.raw_conn is None:
            return
        try:
            if self._context_ends_transaction() and exc_type is None:
                self.commit()
            elif self._context_ends_transaction():
                # put() keeps a carried connection and its transaction open.
                # A failing rollback must not hide the block's exception.
                with suppress(Exception):
                    self.rollback()
        finally:
            if self.conn:
                self.put()

    def __call__(self, autocommit: bool = False) -> Self:
        self.create_cursor(autocommit=autocommit)
        self._opened_by_call = True
        return self

    def create_cursor(self, autocommit: bool = False) -> Self:
        if self._open:
            # A second connection would replace the first, which stays
            # checked out for good.
            raise exc.APIError("The cursor is already open.")
        conn = self._conn()
        if self.carrier is None:
            self._attach_new(conn, autocommit)
        else:
            # Other threads on this carrier wait for its connection instead
            # of opening another one.
            with self.carrier.lock:
                raw_conn = self._carried_raw_conn()
                if raw_conn is None:
                    self._attach_new(conn, autocommit)
                else:
                    self._attach(conn, raw_conn)
        self._open = True
        return self

    def _attach_new(self, conn: ConnectionLike, autocommit: bool) -> None:
        raw_conn = translating(conn, conn.get)(
            autocommit=self._autocommit(autocommit)
        )
        try:
            self._attach(conn, raw_conn)
        except BaseException:
            conn.put(raw_conn)
            raise

    def put(self, force: bool = False) -> None:
        """
        Ensures that not only the cursor is closed but also
        the connection if necessary.

        If the connection is bound to the carrier it
        needs to be returned manually.

        If :param:`force` is set to True return is anyway
        """
        if self.raw_conn is None or self.raw_cursor is None:
            return
        self._open = False
        try:
            close_occupants(self.raw_conn, self)
            try:
                self.raw_cursor.close()
            except exc.ConnectionLost:
                # Returning the connection discards it. An error here would
                # hide the exception that left the block.
                pass
            except Exception:
                # mysqlclient reports a failing later statement here, but
                # also fails while another cursor's stream occupies the
                # connection, which must not hide the block's exception.
                if not blocked(self.raw_conn):
                    raise
        finally:
            detached = self._detach(force)
            if detached is not None:
                conn, raw_conn = detached
                conn.put(raw_conn)

    def close(self) -> None:
        self.put(force=True)

    def _driver_attr(self, value: Any) -> Any:
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            result = value(*args, **kwargs)
            if inspect.isgenerator(result):
                use = Occupation(self, result.close)
                advance = translating(self._conn(), next)
                return DriverIterator(use, lambda: advance(result))
            # psycopg's execute() returns its cursor, a context manager too.
            if hasattr(type(result), "__exit__") and (
                self.raw_cursor is None or result is not self.raw_cursor.cursor
            ):
                return DriverContext(self, result)
            return result

        return call

    def _lose_carried(self) -> None:
        if self.raw_conn is not None and self.raw_cursor is not None:
            # Queries would run on a connection back in the pool.
            with suppress(Exception):
                self.raw_cursor.close()
        super()._lose_carried()

    def commit(self) -> None:
        self._end_transaction("commit")

    def rollback(self) -> None:
        self._end_transaction("rollback")

    @contextmanager
    def transaction(self) -> Generator[None, None, None]:
        """Run a block atomically: commit at its end, or roll back if an
        exception leaves it. Inside another block it uses a savepoint and
        undoes only its own work. See :ref:`transaction-blocks`.
        """
        block = Block(self)
        block.begin()
        try:
            yield
            block.commit()
        except BaseException:
            # A failing rollback must not hide the block's exception.
            with suppress(Exception):
                block.rollback()
            raise
        finally:
            block.forget()

    def _run_script(
        self, script: str | None, content: str, params: Params
    ) -> None:
        self._cursor()._run_script(script, content, params)

    def query(
        self,
        content: str,
        *args: Any,
        is_template: bool = False,
        **kwargs: Any,
    ) -> Query:
        """
        Creates an ad hoc Query object based on content.
        """
        script = self._script(content, is_template)
        return self._query(script, args, kwargs, self.db.prepare_params)

    def _query(
        self,
        script: Script,
        args: Sequence[Any],
        kwargs: dict[str, Any],
        prepare_params: PrepareParams | None,
    ) -> Query:
        return Query(script, self, args, kwargs, prepare_params)
