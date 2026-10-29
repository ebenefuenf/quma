from __future__ import annotations

from collections.abc import Sequence
from contextlib import suppress
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
from .namespace import (
    CursorNamespace,
    Namespace,
    get_namespace,
)
from .query import (
    BaseQuery,
    Query,
)
from .script import (
    PrepareParams,
    Script,
)

if TYPE_CHECKING:
    from .database import (
        BaseDatabase,
        Carrier,
    )


class CarriedConnection(Generic[ConnT]):
    def __init__(self, conn: ConnT, raw_conn: RawConnection) -> None:
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper:
    def __init__(
        self, conn: BaseConnectionLike, raw_cursor: RawCursor
    ) -> None:
        self.conn = conn
        self.cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key: str) -> Any:
        return self.conn.get_cursor_attr(self.cursor, key)


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
        self.autocommit = isinstance(autocommit, bool) and autocommit
        self.raw_conn: RawConnection | None = None
        self.raw_cursor: RawCursorWrapper | None = None
        self.contextcommit = contextcommit
        self._opened_by_call = False

    def _autocommit(self, autocommit: bool) -> bool:
        if isinstance(autocommit, bool) and autocommit:
            return True
        return self.autocommit

    def _carried_raw_conn(self) -> RawConnection | None:
        if self.carrier and self.carrier.conn:
            return self.carrier.conn.raw_conn
        return None

    def _attach(self, conn: ConnT, raw_conn: RawConnection) -> None:
        raw_cursor = conn.cursor(raw_conn)
        if self.carrier:
            if not self.carrier.conn:
                self.carrier.add_conn(CarriedConnection(conn, raw_conn))
            self.carrier.cursors.add(self)
        self.raw_conn = raw_conn
        self.raw_cursor = RawCursorWrapper(conn, raw_cursor)

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

    def _conn(self) -> ConnT:
        if self.conn is None:
            raise exc.APIError("The database is closed.")
        return self.conn

    def _raw_conn(self) -> RawConnection:
        if self.raw_conn is None:
            raise exc.APIError("The cursor has no open connection.")
        return self.raw_conn

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
        return self._conn().mogrify(self.raw_cursor, content, params)

    def __getattr__(self, attr: str) -> Any:
        try:
            value = getattr(self.raw_cursor, attr)
        except AttributeError:
            pass
        else:
            return self._driver_attr(value)
        try:
            return CursorNamespace(get_namespace(self, attr), self)
        except AttributeError as e:
            raise AttributeError(
                "Namespace, Root method, or cursor "
                f'attribute "{attr}" not found.'
            ) from e


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
            if self.contextcommit and exc_type is None:
                self.commit()
            elif self.contextcommit:
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
        conn = self._conn()
        raw_conn = self._carried_raw_conn()
        if raw_conn is not None:
            self._attach(conn, raw_conn)
            return self
        raw_conn = conn.get(autocommit=self._autocommit(autocommit))
        try:
            self._attach(conn, raw_conn)
        except BaseException:
            conn.put(raw_conn)
            raise
        return self

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
        try:
            self.raw_cursor.close()
        finally:
            detached = self._detach(force)
            if detached is not None:
                conn, raw_conn = detached
                conn.put(raw_conn)

    def close(self) -> None:
        self.put(force=True)

    def _lose_carried(self) -> None:
        if self.raw_conn is not None and self.raw_cursor is not None:
            # Queries would run on a connection back in the pool.
            with suppress(Exception):
                self.raw_cursor.close()
        super()._lose_carried()

    def commit(self) -> None:
        self._raw_conn().commit()

    def rollback(self) -> None:
        self._raw_conn().rollback()

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
