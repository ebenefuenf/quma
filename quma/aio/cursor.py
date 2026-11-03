from __future__ import annotations

import asyncio
import inspect
from collections.abc import (
    AsyncGenerator,
    Awaitable,
    Callable,
    Generator,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    asynccontextmanager,
    nullcontext,
    suppress,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Self,
)

from .. import exc
from ..conn import (
    AsyncConnectionLike,
    Params,
)
from ..cursor import BaseCursor
from ..errors import translating
from ..namespace import Namespace
from ..occupation import aclose_occupants
from ..script import (
    PrepareParams,
    Script,
)
from .occupation import (
    AsyncDriverContext,
    AsyncDriverIterator,
    AsyncOccupation,
)
from .query import AsyncQuery
from .transaction import AsyncBlock

if TYPE_CHECKING:
    from ..database import (
        BaseDatabase,
        Carrier,
    )


# The event loop only holds weak references to its tasks.
_finishing: set[asyncio.Task[None]] = set()


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
        # Held while an operation runs; two tasks on one DB-API cursor
        # would read each other's results.
        self._busy = asyncio.Lock()
        self._call_autocommit = False
        # A driver's copy running in a block, which holds _busy.
        self._block: AsyncOccupation | None = None

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
            if self._context_ends_transaction() and exc_type is None:
                await self.commit()
            elif self._context_ends_transaction():
                # put() keeps a carried connection and its transaction open.
                # A failing rollback must not hide the block's exception.
                with suppress(Exception):
                    await self.rollback()
        finally:
            if self.conn:
                await self.put()

    async def _open_cursor(self) -> Self:
        autocommit, self._call_autocommit = self._call_autocommit, False
        return await self.create_cursor(autocommit=autocommit)

    async def create_cursor(self, autocommit: bool = False) -> Self:
        if self._open:
            # A second connection would replace the first, which stays
            # checked out for good.
            raise exc.APIError("The cursor is already open.")
        conn = self._conn()
        # Before the first await, for a second task on this cursor.
        self._open = True
        try:
            if self.carrier is None:
                await self._attach_new(conn, autocommit)
            else:
                # Other tasks on this carrier wait for its connection instead
                # of taking another pool slot.
                async with self.carrier.alock:
                    raw_conn = self._carried_raw_conn()
                    if raw_conn is None:
                        await self._attach_new(conn, autocommit)
                    else:
                        self._attach(conn, raw_conn)
        except BaseException:
            self._open = False
            raise
        return self

    async def _attach_new(
        self, conn: AsyncConnectionLike, autocommit: bool
    ) -> None:
        raw_conn = await translating(conn, conn.get)(
            autocommit=self._autocommit(autocommit)
        )
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
        try:
            await self._put_when_idle(force)
        except asyncio.CancelledError:
            # Still waiting for the operation, and only put() returns the
            # connection to its pool.
            if self._open:
                task = asyncio.create_task(self._put_when_idle(force))
                _finishing.add(task)
                task.add_done_callback(_finishing.discard)
            raise

    async def _put_when_idle(self, force: bool) -> None:
        # This task's own block would wait for itself.
        block = self._block
        if block is not None and block.task is asyncio.current_task():
            await block.close()
        # Waits for a running operation instead of closing under it.
        async with self._busy, self._shared():
            if self.raw_conn is None or self.raw_cursor is None:
                return
            self._open = False
            try:
                await aclose_occupants(self.raw_conn, self)
                # Returning the connection discards it. An error here would
                # hide the exception that left the block.
                with suppress(exc.ConnectionLost):
                    await self.raw_cursor.close()
            finally:
                detached = self._detach(force)
                if detached is not None:
                    conn, raw_conn = detached
                    await conn.put(raw_conn)

    async def close(self) -> None:
        await self.put(force=True)

    async def commit(self) -> None:
        await self._guarded(lambda: self._end_transaction("commit"))

    async def rollback(self) -> None:
        await self._guarded(lambda: self._end_transaction("rollback"))

    @asynccontextmanager
    async def transaction(self) -> AsyncGenerator[None, None]:
        """Run a block atomically: commit at its end, or roll back if an
        exception leaves it. Inside another block it uses a savepoint and
        undoes only its own work. See :ref:`transaction-blocks`.
        """
        block = AsyncBlock(self)
        await block.begin()
        try:
            yield
            await block.commit()
        except BaseException:
            # A failing rollback must not hide the block's exception.
            with suppress(Exception):
                await block.rollback()
            raise
        finally:
            block.forget()

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guarded(
            lambda: self._cursor().execute(*args, **kwargs)
        )

    async def fetchone(self) -> Any:
        return await self._guarded(lambda: self._cursor().fetchone())

    async def fetchmany(self, *args: Any, **kwargs: Any) -> Any:
        return await self._guarded(
            lambda: self._cursor().fetchmany(*args, **kwargs)
        )

    async def fetchall(self) -> Any:
        return await self._guarded(lambda: self._cursor().fetchall())

    async def _run_script(
        self, script: str | None, content: str, params: Params
    ) -> None:
        await self._guarded(
            lambda: self._cursor()._run_script(script, content, params)
        )

    async def _guarded(self, call: Callable[[], Awaitable[Any]]) -> Any:
        self._check_idle()
        async with self._busy, self._shared():
            return await call()

    def _check_idle(self) -> None:
        if self._busy.locked():
            raise exc.APIError(
                "The cursor is busy with another query. "
                "Open one cursor per task."
            )

    def _shared(self) -> AbstractAsyncContextManager[Any]:
        # Cursors on one carrier share its connection, and asyncmy can't
        # run two queries on a connection at once.
        if self.carrier is None:
            return nullcontext()
        return self.carrier.alock

    def _driver_attr(self, value: Any) -> Any:
        if not callable(value):
            return value

        def call(*args: Any, **kwargs: Any) -> Any:
            self._cursor()
            self._check_idle()
            result = value(*args, **kwargs)
            if inspect.isawaitable(result):
                return self._guarded(lambda: result)
            if hasattr(result, "__aenter__"):
                return AsyncDriverContext(self, result)
            if hasattr(result, "__anext__"):
                return AsyncDriverIterator(self, result)
            return result

        return call

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
