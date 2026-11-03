from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from .. import exc
from ..errors import translating
from ..occupation import (
    CLOSED_EARLY,
    BaseOccupation,
)


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
