from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
)

from .. import exc
from ..conn import (
    Params,
    Row,
)
from ..errors import translating
from ..stream import (
    CLOSED_EARLY,
    INTRANS,
    BaseOccupation,
    BaseStream,
    blocked,
    check_idle,
)

if TYPE_CHECKING:
    from ..query import BaseQuery


class AsyncStream(BaseStream):
    def __init__(self, query: BaseQuery, size: int) -> None:
        super().__init__(query, size)
        self.task = asyncio.current_task()

    async def open(self) -> None:
        content, params = self._prepare()
        await self.cursor._guarded(lambda: self._execute(content, params))

    async def _execute(self, content: str, params: Params) -> None:
        self._open()
        script = self.query.script
        try:
            await self._send(content, params)
        finally:
            script.echo and script.mogrify(self, content, params)
        if not self.postgres:
            self.description = self.raw.description
            self.done = self.description is None

    async def fetch(self) -> Sequence[Row]:
        if self.done:
            return ()
        self._check_open()
        return await self.cursor._guarded(self._fetch)

    async def _fetch(self) -> Sequence[Row]:
        # The cursor may have closed it while this waited for its turn.
        self._check_open()
        if self.postgres:
            check_idle(self.raw_conn)
            await self._attr("execute")(self._batch())
            rows = await self._attr("fetchall")()
            self.description = self.raw.description
        else:
            rows = await self._attr("fetchmany")(self.size)
        if self._ended(rows):
            await self.close()
        return rows

    async def finish(self) -> None:
        """Close the stream if its loop ended early."""
        # Python closes an abandoned async generator later, in a task of
        # its own, which would race the cursor's next query. The cursor or
        # the return of its connection closes the stream then.
        if self.raw is None or asyncio.current_task() is not self.task:
            return
        with suppress(Exception):
            await self.cursor._guarded(self.close)

    async def close(self) -> None:
        raw, self.raw = self.raw, None
        if raw is None:
            return
        try:
            # The end of the transaction closes the server-side cursor, and
            # a MySQL connection that can't be read to the end is discarded.
            with suppress(Exception):
                if self.postgres and not blocked(self.raw_conn):
                    await self._close_portal(raw)
                await raw.close()
        finally:
            self._forget()

    async def _close_portal(self, raw: Any) -> None:
        execute = self.conn.get_cursor_attr(raw, "execute")
        if not self.done:
            # A commit or rollback since the last batch has closed it, and
            # closing it again would fail and abort the transaction.
            if self.raw_conn.info.transaction_status != INTRANS:
                return
            await execute(
                "SELECT 1 FROM pg_catalog.pg_cursors WHERE name = %s",
                [self.name],
            )
            if not await self.conn.get_cursor_attr(raw, "fetchall")():
                return
        await execute(f'CLOSE "{self.name}"')


class AsyncOccupation(BaseOccupation):
    def __init__(self, cursor: Any, finish: Any) -> None:
        super().__init__(cursor, finish)
        self.task = asyncio.current_task()

    async def close(self) -> None:
        if self.forget():
            # A lost connection can't finish it, and is discarded anyway.
            with suppress(Exception):
                await self.finish()


class AsyncDriverIterator:
    """What psycopg's ``cursor.stream()`` returns. It takes the cursor's lock
    for each row only, so that closing the cursor can end the stream."""

    def __init__(self, cursor: Any, iterator: Any) -> None:
        self.cursor = cursor
        self.iterator = iterator
        self.use = AsyncOccupation(cursor, iterator.aclose)

    def __aiter__(self) -> AsyncDriverIterator:
        return self

    async def __anext__(self) -> Any:
        if self.use.closed:
            raise exc.APIError(CLOSED_EARLY)
        return await self.cursor._guarded(self._next)

    async def _next(self) -> Any:
        # The cursor may have closed it while this waited for its turn.
        if self.use.closed:
            raise exc.APIError(CLOSED_EARLY)
        conn = self.cursor._conn()
        try:
            return await translating(conn, self.iterator.__anext__)()
        except BaseException:
            await self.use.close()
            raise

    async def aclose(self) -> None:
        await self.cursor._guarded(self.use.close)


class AsyncDriverContext:
    """What psycopg's ``cursor.copy()`` returns. It holds the cursor's lock for
    the whole block: its object runs on the connection without asking, and
    another task closing the cursor has to wait for it."""

    def __init__(self, cursor: Any, manager: Any) -> None:
        self.cursor = cursor
        self.manager = manager
        self.use: AsyncOccupation

    async def __aenter__(self) -> Any:
        cursor = self.cursor
        cursor._check_idle()
        await cursor._busy.acquire()
        try:
            self.use = AsyncOccupation(cursor, self._abort)
            enter = translating(cursor._conn(), self.manager.__aenter__)
            try:
                async with cursor._shared():
                    value = await enter()
            except BaseException:
                self.use.forget()
                raise
        except BaseException:
            cursor._busy.release()
            raise
        cursor._block = self.use
        return value

    async def __aexit__(self, *exc_info: Any) -> Any:
        if not self.use.forget():
            return False
        self.cursor._block = None
        leave = translating(self.cursor._conn(), self.manager.__aexit__)
        try:
            return await leave(*exc_info)
        finally:
            self.cursor._busy.release()

    async def _abort(self) -> None:
        self.cursor._block = None
        # Only with an exception does psycopg stop the COPY, and without
        # ending it the next statement waits for its rest.
        error = exc.APIError(CLOSED_EARLY)
        try:
            await self.manager.__aexit__(type(error), error, None)
        finally:
            self.cursor._busy.release()
