from __future__ import annotations

from collections.abc import (
    Generator,
    Sequence,
)
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
    Self,
)

from .. import exc
from ..conn import AsyncConnectionLike
from ..cursor import BaseCursor
from ..namespace import Namespace
from ..script import (
    PrepareParams,
    Script,
)
from .query import AsyncQuery

if TYPE_CHECKING:
    from ..database import (
        BaseDatabase,
        Carrier,
    )


class AsyncCursor(BaseCursor[AsyncConnectionLike]):
    def __init__(
        self,
        db: BaseDatabase[AsyncConnectionLike],
        namespaces: dict[str, Namespace],
        contextcommit: bool,
        carrier: Carrier | None = None,
        autocommit: bool = False,
    ) -> None:
        super().__init__(
            db,
            namespaces,
            contextcommit,
            carrier=carrier,
            autocommit=autocommit,
        )
        self._busy = False
        self._open = False
        self._call_autocommit = False

    def __call__(self, autocommit: bool = False) -> Self:
        # Calling can't await: `async with` or `await` opens the cursor.
        self._call_autocommit = autocommit
        return self

    def __await__(self) -> Generator[Any, None, Self]:
        return self._open_by_call().__await__()

    async def _open_by_call(self) -> Self:
        await self._open_cursor()
        self._opened_by_call = True
        return self

    async def __aenter__(self) -> Self:
        # `async with await db.cursor() as cur` uses the open connection.
        if self._opened_by_call:
            self._opened_by_call = False
            return self
        return await self._open_cursor()

    async def __aexit__(
        self, exc_type: type[BaseException] | None, *args: object
    ) -> None:
        if self.raw_conn is None:
            return
        try:
            if self.contextcommit and exc_type is None:
                await self.commit()
            elif self.contextcommit:
                # put() keeps a carried connection and its transaction open.
                # A failing rollback must not hide the block's exception.
                with suppress(Exception):
                    await self.rollback()
        finally:
            if self.conn:
                await self.put()

    async def _open_cursor(self) -> Self:
        if self._open:
            raise exc.APIError("The cursor is already open.")
        autocommit, self._call_autocommit = self._call_autocommit, False
        return await self.create_cursor(autocommit=autocommit)

    async def create_cursor(self, autocommit: bool = False) -> Self:
        conn = self._conn()
        if self.carrier is None:
            await self._attach_new(conn, autocommit)
        else:
            # Other tasks on this carrier wait for its connection instead
            # of taking another pool slot.
            async with self.carrier.opening:
                raw_conn = self._carried_raw_conn()
                if raw_conn is None:
                    await self._attach_new(conn, autocommit)
                else:
                    self._attach(conn, raw_conn)
        self._open = True
        return self

    async def _attach_new(
        self, conn: AsyncConnectionLike, autocommit: bool
    ) -> None:
        raw_conn = await conn.get(autocommit=self._autocommit(autocommit))
        try:
            self._attach(conn, raw_conn)
        except BaseException:
            await conn.put(raw_conn)
            raise

    async def put(self, force: bool = False) -> None:
        """
        Close the cursor and return the connection, unless a carrier
        holds it. With ``force`` the carrier releases it too.
        """
        if self.raw_conn is None or self.raw_cursor is None:
            return
        self._open = False
        try:
            await self.raw_cursor.close()
        finally:
            detached = self._detach(force)
            if detached is not None:
                conn, raw_conn = detached
                await conn.put(raw_conn)

    async def close(self) -> None:
        await self.put(force=True)

    async def commit(self) -> None:
        self._check_idle()
        await self._raw_conn().commit()

    async def rollback(self) -> None:
        self._check_idle()
        await self._raw_conn().rollback()

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await self._io("execute", *args, **kwargs)

    async def fetchone(self) -> Any:
        return await self._io("fetchone")

    async def fetchmany(self, *args: Any, **kwargs: Any) -> Any:
        return await self._io("fetchmany", *args, **kwargs)

    async def fetchall(self) -> Any:
        return await self._io("fetchall")

    async def _io(self, name: str, *args: Any, **kwargs: Any) -> Any:
        if self.raw_cursor is None:
            raise exc.APIError("The cursor has no open connection.")
        self._check_idle()
        self._busy = True
        try:
            return await getattr(self.raw_cursor, name)(*args, **kwargs)
        finally:
            self._busy = False

    def _check_idle(self) -> None:
        # Two tasks on one DB-API cursor would read each other's results.
        if self._busy:
            raise exc.APIError(
                "The cursor is busy with another query. "
                "Open one cursor per task."
            )

    def query(
        self,
        content: str,
        *args: Any,
        is_template: bool = False,
        **kwargs: Any,
    ) -> AsyncQuery:
        """
        Creates an ad hoc AsyncQuery object based on content.
        """
        script = self._script(content, is_template)
        return self._query(script, args, kwargs, self.db.prepare_params)

    def _query(
        self,
        script: Script,
        args: Sequence[Any],
        kwargs: dict[str, Any],
        prepare_params: PrepareParams | None,
    ) -> AsyncQuery:
        return AsyncQuery(script, self, args, kwargs, prepare_params)
