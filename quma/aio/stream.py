from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextlib import suppress
from typing import (
    TYPE_CHECKING,
    Any,
)

from ..conn import (
    Params,
    Row,
)
from ..occupation import (
    blocked,
    check_idle,
)
from ..stream import (
    INTRANS,
    BaseStream,
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
