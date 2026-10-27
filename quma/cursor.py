from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    Self,
)

from . import exc
from .conn import (
    ConnectionLike,
    Params,
    RawConnection,
    RawCursor,
)
from .namespace import (
    CursorNamespace,
    Namespace,
    get_namespace,
)
from .query import Query
from .script import Script

if TYPE_CHECKING:
    from .database import (
        Carrier,
        Database,
    )


class CarriedConnection:
    def __init__(self, conn: ConnectionLike, raw_conn: RawConnection) -> None:
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper:
    def __init__(self, conn: ConnectionLike, raw_cursor: RawCursor) -> None:
        self.conn = conn
        self.cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key: str) -> Any:
        return self.conn.get_cursor_attr(self.cursor, key)


class Cursor:
    def __init__(
        self,
        db: Database,
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

    def __enter__(self) -> Self:
        # `with db.cursor() as cur` uses the connection opened by the call.
        if self._opened_by_call:
            self._opened_by_call = False
            return self
        return self.create_cursor()

    def __exit__(self, *args: object) -> None:
        if self.raw_conn is None:
            return
        if self.contextcommit:
            self.commit()
        if self.conn:
            self.put()

    def __call__(self, autocommit: bool = False) -> Self:
        self.create_cursor(autocommit=autocommit)
        self._opened_by_call = True
        return self

    def create_cursor(self, autocommit: bool = False) -> Self:
        autocommit = (
            True
            if isinstance(autocommit, bool) and autocommit
            else self.autocommit
        )
        conn = self._conn()
        if self.carrier:
            if self.carrier.conn:
                self.raw_conn = self.carrier.conn.raw_conn
            else:
                raw_conn = conn.get(autocommit=autocommit)
                self.carrier.add_conn(CarriedConnection(conn, raw_conn))
                self.raw_conn = raw_conn
        else:
            self.raw_conn = conn.get(autocommit=autocommit)
        self.raw_cursor = RawCursorWrapper(conn, conn.cursor(self.raw_conn))
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
        self.raw_cursor.close()

        if self.carrier and self.carrier.conn:
            if not force:
                return
            self.carrier.release()
            self.carrier = None
        else:
            self._conn().put(self.raw_conn)
        self.raw_conn = None
        self._opened_by_call = False

    def close(self) -> None:
        self.put(force=True)

    def commit(self) -> None:
        self._raw_conn().commit()

    def rollback(self) -> None:
        self._raw_conn().rollback()

    def _conn(self) -> ConnectionLike:
        if self.conn is None:
            raise exc.APIError("The database is closed.")
        return self.conn

    def _raw_conn(self) -> RawConnection:
        if self.raw_conn is None:
            raise exc.APIError("The cursor has no open connection.")
        return self.raw_conn

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
        script = Script(
            content,
            self.db.echo,
            is_template,
            self.db.sqldirs,
            self.db.prepare_params,
        )
        return Query(script, self, args, kwargs, self.db.prepare_params)

    def get_conn_attr(self, attr: str) -> Any:
        return getattr(self.raw_conn, attr)

    def set_conn_attr(self, attr: str, value: Any) -> None:
        setattr(self.raw_conn, attr, value)

    def mogrify(self, content: str, params: Params) -> str:
        return self._conn().mogrify(self.raw_cursor, content, params)

    def __getattr__(self, attr: str) -> Any:
        try:
            return getattr(self.raw_cursor, attr)
        except AttributeError:
            pass
        try:
            return CursorNamespace(get_namespace(self, attr), self)
        except AttributeError as e:
            raise AttributeError(
                "Namespace, Root method, or cursor "
                f'attribute "{attr}" not found.'
            ) from e
