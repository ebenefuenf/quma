try:
    import asyncmy
    from asyncmy.cursors import (
        Cursor,
        DictCursor,
    )
    from asyncmy.errors import (
        Error,
        OperationalError,
    )
except ImportError as e:
    raise ImportError(
        "In order to use quma with asyncmy you need to install asyncmy"
    ) from e

from .. import (
    conn,
    exc,
)


class AsyncConnection(conn.AsyncConnection):
    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 3306
        if kwargs.pop("dict_cursor", False):
            self.cursor_factory = DictCursor
        else:
            self.cursor_factory = Cursor

    def get_cursor_attr(self, cursor, key):
        if key in ("fetchall", "fetchmany"):

            async def fetch(*args, **kwargs):
                rows = await getattr(cursor, key)(*args, **kwargs)
                # asyncmy returns a list after statements without a
                # result, mysqlclient an empty tuple.
                if cursor.description is None:
                    return ()
                return rows

            return fetch
        return getattr(cursor, key)

    async def create_conn(self, **kwargs):
        try:
            conn = await asyncmy.connect(
                database=self.database,
                user=self.username,
                password=self.password,
                host=self.hostname,
                port=self.port,
                cursor_cls=self.cursor_factory,
                **kwargs,
            )
        except OperationalError as e:
            raise exc.ConnectionError(e) from e
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

    async def _check(self, conn):
        try:
            await conn.ping(reconnect=False)
        except Error as e:
            raise exc.OperationalError from e
