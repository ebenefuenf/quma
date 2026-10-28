from __future__ import annotations

from collections.abc import (
    Callable,
    Sequence,
)
from types import ModuleType
from typing import (
    Any,
    Self,
)

from ..conn import (
    AsyncConnectionLike,
    Row,
)
from ..database import (
    BaseCallWrapper,
    BaseDatabase,
    resolve,
)
from ..exc import APIError
from ..namespace import Namespace
from ..script import (
    PrepareParams,
    Script,
    SqlDirs,
)
from .cursor import AsyncCursor
from .pool import AsyncPool


class AsyncDatabaseCallWrapper(BaseCallWrapper):
    @property
    def cursor(self) -> AsyncCursor:
        return AsyncCursor(
            self.database,
            self.database.namespaces,
            self.database.contextcommit,
            carrier=self.carrier,
            autocommit=self.autocommit,
        )


class AsyncDatabase(BaseDatabase[AsyncConnectionLike]):
    """
    The async counterpart of :class:`quma.Database`, with the same
    parameters. It works with drivers that support asyncio, currently
    psycopg 3 (``psycopg://`` and ``psycopg+pool://``).

    Creating it does no I/O: connections open on first use, including
    the persistent one. Call :meth:`open` to connect at startup, and
    :meth:`close` when you're done, or use it with ``async with``.

    In SQL directories, a class ``Async<Name>`` takes precedence over
    ``<Name>``, so one directory can hold sync and async namespace
    classes.
    """

    def __init__(
        self,
        dburi: str,
        sqldirs: SqlDirs = (),
        *args: Any,
        file_ext: str = "sql",
        tmpl_ext: str = "msql",
        script_factory: Callable[..., Script] = Script,
        prepare_params: PrepareParams | None = None,
        contextcommit: bool = False,
        echo: bool = False,
        cache: bool = False,
        **kwargs: Any,
    ) -> None:
        if args:
            raise ValueError("Max number of arguments is two")
        # The remaining kwargs are passed to the DBAPI connect call
        self.conn = connect_async(dburi, **kwargs)
        super().__init__(
            sqldirs,
            file_ext=file_ext,
            tmpl_ext=tmpl_ext,
            script_factory=script_factory,
            prepare_params=prepare_params,
            contextcommit=contextcommit,
            echo=echo,
            cache=cache,
        )

    def __call__(
        self, carrier: object | None = None, autocommit: bool = False
    ) -> AsyncDatabaseCallWrapper:
        return AsyncDatabaseCallWrapper(
            self, carrier=carrier, autocommit=autocommit
        )

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()

    def _namespace_class(
        self, module: ModuleType, class_name: str
    ) -> type[Namespace]:
        ns_class = getattr(module, "Async" + class_name, None)
        if ns_class is None:
            return super()._namespace_class(module, class_name)
        return ns_class

    async def open(self) -> None:
        """Connect now instead of on first use: open the persistent
        connection, or open one connection and return it to the pool.
        Wrong credentials then fail at startup."""
        if self.conn is None:
            raise APIError("The database is closed.")
        await self.conn.open()

    async def execute(self, query: str, **kwargs: Any) -> Sequence[Row] | None:
        """Execute the statements in ``query`` and commit
        immediately.

        :param query: The sql query to execute.
        """
        result = None
        cur = await self.cursor()
        try:
            await cur.execute(query, **kwargs)
            await cur.commit()
            if cur.description:
                result = await cur.fetchall()
        except Exception:
            await cur.rollback()
            raise
        finally:
            await cur.close()
        return result

    async def close(self) -> None:
        """Close (all) open connections. If you want to reconnect you
        need to create a new :class:`quma.AsyncDatabase` instance.

        Calling it again, or on a database without persistent or pooled
        connections, does nothing.
        """
        if self.conn is not None:
            await self.conn.close()
            self.conn = None

    async def release(self, carrier: object) -> None:
        """If the ``carrier`` holds a connection close it or return
        it to the pool.

        :param carrier: An object holding a quma connection. See
            :doc:`Reusing connections <carrier>`
        """
        carried = self.heap.pop(id(carrier))
        if carried is not None:
            await carried.conn.put(carried.raw_conn)

    @property
    def cursor(self) -> AsyncCursor:
        """Return a cursor; ``async with`` or ``await`` opens it."""
        return AsyncCursor(self, self.namespaces, self.contextcommit)


def connect_async(dburi: str, **kwargs: Any) -> AsyncConnectionLike:
    """
    Create and return an async Connection or AsyncPool object specified
    via ``dburi`` (a string in the form of an URL)
    """
    module, url, pooled = resolve(dburi)
    conn_class = getattr(module, "AsyncConnection", None)
    if conn_class is None:
        name = module.__name__.rsplit(".", 1)[-1]
        raise ValueError(
            f'The driver "{name}" has no async support. Use psycopg://'
        )
    if pooled:
        return AsyncPool(conn_class, url, **kwargs)
    return conn_class(url, **kwargs)
