from __future__ import annotations

from ..transaction import BaseBlock


class AsyncBlock(BaseBlock):
    async def begin(self) -> None:
        statements = self._begin_statements()
        await self.cursor._guarded(lambda: self._run(statements))
        self._register()

    async def commit(self) -> None:
        self._check_commit()
        statements = self._commit_statements()
        await self.cursor._guarded(lambda: self._run(statements))
        if self._driver_ends:
            await self.cursor._guarded(self.raw_conn.commit)

    async def rollback(self) -> None:
        if not self.ended:
            await self.cursor._guarded(self._rollback)

    async def _rollback(self) -> None:
        for stream in self._blocking_streams():
            await stream.close()
        await self._run(self._rollback_statements())
        if self._driver_ends:
            await self.raw_conn.rollback()

    async def _run(self, statements: tuple[str, ...]) -> None:
        for statement in statements:
            raw = self.conn.cursor(self.raw_conn)
            try:
                await self.conn.get_cursor_attr(raw, "execute")(statement)
            finally:
                await raw.close()
