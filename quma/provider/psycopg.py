try:
    import psycopg
except ImportError as e:
    raise ImportError(
        "In order to use quma with PostgreSQL you need to install psycopg"
    ) from e

from functools import partial

from psycopg.pq import TransactionStatus

from .. import (
    conn,
    errors,
    exc,
)
from ..rows import (
    ChangelingRow,
    Row,
    column_index,
)


def row_factory(row_class):
    def factory(cursor):
        return partial(row_class, index=column_index(cursor.description))

    return factory


class Cursor(psycopg.ClientCursor):
    def execute(self, query, params=None, **kwargs):
        super().execute(query, params, **kwargs)
        # Like psycopg2, expose the result of the last statement
        # if the query consists of multiple statements.
        while self.nextset():
            pass
        return self


class AsyncCursor(psycopg.AsyncClientCursor):
    async def execute(self, query, params=None, **kwargs):
        await super().execute(query, params, **kwargs)
        while self.nextset():
            pass
        return self


class BaseConnection(conn.PostgresTransactions, conn.BaseConnection):
    dialect = "postgresql"
    driver_error = psycopg.Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)

        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 5432
        if self.changeling:
            self.factory = row_factory(ChangelingRow)
        else:
            self.factory = row_factory(Row)

    def connect_kwargs(self, kwargs):
        return dict(
            dbname=self.database,
            user=self.username,
            password=self.password,
            host=self.hostname,
            port=self.port,
            row_factory=self.factory,
            **kwargs,
        )


class Connection(BaseConnection, conn.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)
        self._init_conn()

    def get_cursor_attr(self, cursor, key):
        if key in ("fetchall", "fetchmany"):

            def fetch(*args, **kwargs):
                try:
                    return getattr(cursor, key)(*args, **kwargs)
                except psycopg.ProgrammingError:
                    # PostgreSQL drivers raise an error when fetchall is
                    # called after a CREATE, INSERT, UPDATE and so on.
                    # mysqlclient and sqlite3 return an empty tuple. We do
                    # it that way too to provide an uniform api.
                    if cursor.description is None:
                        return ()
                    raise

            return fetch
        return getattr(cursor, key)

    def create_conn(self, **kwargs):
        try:
            return psycopg.connect(
                cursor_factory=Cursor, **self.connect_kwargs(kwargs)
            )
        except psycopg.Error as e:
            raise errors.connection_error(e, self.dialect) from e

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.autocommit = True
        return conn

    def disable_autocommit(self, conn):
        conn.autocommit = False
        return conn

    def mogrify(self, cursor, content, params):
        # ClientCursor.mogrify() discards the cursor's current result.
        with psycopg.ClientCursor(cursor.connection) as mogrifier:
            return mogrifier.mogrify(content, params)

    def _check(self, conn):
        idle = conn.info.transaction_status == TransactionStatus.IDLE
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except psycopg.OperationalError as e:
            raise exc.ConnectionLost(str(e)) from e
        if idle:
            # End the check's transaction, it would block enabling autocommit.
            conn.rollback()


class AsyncConnection(BaseConnection, conn.AsyncConnection):
    def get_cursor_attr(self, cursor, key):
        if key in ("fetchall", "fetchmany"):

            async def fetch(*args, **kwargs):
                try:
                    return await getattr(cursor, key)(*args, **kwargs)
                except psycopg.ProgrammingError:
                    if cursor.description is None:
                        return ()
                    raise

            return fetch
        return getattr(cursor, key)

    async def create_conn(self, **kwargs):
        try:
            return await psycopg.AsyncConnection.connect(
                cursor_factory=AsyncCursor, **self.connect_kwargs(kwargs)
            )
        except psycopg.Error as e:
            raise errors.connection_error(e, self.dialect) from e

    async def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            await conn.set_autocommit(True)
        return conn

    async def disable_autocommit(self, conn):
        await conn.set_autocommit(False)
        return conn

    def mogrify(self, cursor, content, params):
        # Like the sync mogrify, but closing an async cursor would need an
        # await. A client-side cursor holds nothing that must be released.
        return psycopg.AsyncClientCursor(cursor.connection).mogrify(
            content, params
        )

    async def _check(self, conn):
        idle = conn.info.transaction_status == TransactionStatus.IDLE
        try:
            cur = conn.cursor()
            await cur.execute("SELECT 1")
        except psycopg.OperationalError as e:
            raise exc.ConnectionLost(str(e)) from e
        if idle:
            # End the check's transaction, it would block enabling autocommit.
            await conn.rollback()
