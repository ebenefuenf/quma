try:
    import asyncmy
    from asyncmy.cursors import (
        Cursor,
        SSCursor,
    )
    from asyncmy.errors import Error
except ImportError as e:
    raise ImportError(
        "In order to use quma with asyncmy you need to install asyncmy"
    ) from e

from time import struct_time
from typing import Any

from .. import (
    conn,
    errors,
    exc,
    values,
)
from ..rows import (
    ChangelingRow,
    Row,
    column_index,
)


class Rows:
    row_class = Row

    async def _do_get_result(self: Any):
        await super()._do_get_result()
        self._index = column_index(self.description)
        if self._rows:
            self._rows = [self._conv_row(row) for row in self._rows]

    def _conv_row(self: Any, row):
        if row is None:
            return None
        return self.row_class(row, self._index)


class RowCursor(Rows, Cursor):
    pass


class RowStreamCursor(Rows, SSCursor):
    pass


class ChangelingCursor(RowCursor):
    row_class = ChangelingRow


class ChangelingStreamCursor(RowStreamCursor):
    row_class = ChangelingRow


class EscapingConnection(asyncmy.Connection):
    def escape(self: Any, obj, mapping=None):
        obj = values.plain(obj, self._encoders if mapping is None else mapping)
        # asyncmy escapes these with backslashes byte by byte: under
        # NO_BACKSLASH_ESCAPES or a charset like gbk, a value can end its string.
        # Without _binary, MySQL reads a hex literal as a number in arithmetic.
        if isinstance(obj, bytes):
            return f"_binary X'{obj.hex()}'"
        if isinstance(obj, (tuple, list)) and not isinstance(obj, struct_time):
            items = ",".join(self.escape(item, mapping) for item in obj)
            return f"({items})"
        return super().escape(obj, mapping)


class AsyncConnection(conn.AsyncConnection):
    dialect = "mysql"
    driver_error = Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 3306
        if self.changeling:
            self.cursor_factory = ChangelingCursor
            self.stream_factory = ChangelingStreamCursor
        else:
            self.cursor_factory = RowCursor
            self.stream_factory = RowStreamCursor

    def stream_cursor(self, conn):
        return conn.cursor(self.stream_factory)

    def get_cursor_attr(self, cursor, key):
        if key in ("fetchall", "fetchmany"):

            async def fetch(*args, **kwargs):
                try:
                    rows = await getattr(cursor, key)(*args, **kwargs)
                except Error:
                    # The error ended an unbuffered result, but asyncmy
                    # compares its int flag to True and keeps waiting for
                    # rows, forever.
                    result = getattr(cursor.connection, "_result", None)
                    if result is not None:
                        result.unbuffered_active = False
                    raise
                # asyncmy returns a list after statements without a
                # result, mysqlclient an empty tuple.
                if cursor.description is None:
                    return ()
                return rows

            return fetch
        return getattr(cursor, key)

    async def create_conn(self, **kwargs):
        try:
            conn = EscapingConnection(
                database=self.database,
                user=self.username,
                password=self.password,
                host=self.hostname,
                port=self.port,
                cursor_cls=self.cursor_factory,
                **kwargs,
            )
            await conn.connect()
        except Error as e:
            raise errors.connection_error(e, self.dialect) from e
        return await self.disable_autocommit(conn)

    async def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            await conn.autocommit(True)
        return conn

    async def disable_autocommit(self, conn):
        await conn.autocommit(False)
        return conn

    async def close_conn(self, conn):
        # close() only drops the socket, the server would log an
        # aborted connection.
        await conn.ensure_closed()

    def mogrify(self, cursor, content, params):
        return cursor.mogrify(content, params)

    def in_autocommit(self, conn):
        return conn.get_autocommit()

    def in_transaction(self, conn):
        return bool(conn.get_transaction_status())

    async def _check(self, conn):
        try:
            await conn.ping(reconnect=False)
        except Error as e:
            raise exc.ConnectionLost(str(e)) from e
