from __future__ import annotations

from collections.abc import (
    AsyncIterator,
    Sequence,
)
from typing import (
    Any,
    NoReturn,
    Self,
    overload,
)

from .. import exc
from ..conn import Row
from ..mapping import (
    T,
    Target,
)
from ..query import (
    BaseQuery,
    check_rowcount,
    map_rows,
)


class AsyncManyResult:
    def __init__(self, query: AsyncQuery) -> None:
        self.query = query
        self.cursor = query.cursor
        self._has_been_executed = False

    @overload
    async def get(self, size: int | None = None) -> Sequence[Row]: ...

    @overload
    async def get(
        self, size: int | None = None, target: type[dict[Any, Any]] = ...
    ) -> list[dict[str, Any]]: ...

    @overload
    async def get(
        self, size: int | None = None, target: Target[T] = ...
    ) -> list[T]: ...

    async def get(
        self, size: int | None = None, target: Target[Any] | None = None
    ) -> Sequence[Any]:
        """Call the :func:`fetchmany` method of the raw cursor.

        :param size: The number of rows to be returned. If not
            given use the default value of the driver.
        :param target: Map the rows to instances of this class
            (see :doc:`mapping`).
        """
        size = self.cursor.arraysize if size is None else size
        if not self._has_been_executed:
            await self.query.run()
            self._has_been_executed = True
        rows = await self.cursor.fetchmany(size)
        return map_rows(target, self.cursor.description, rows)


class AsyncQuery(BaseQuery):
    """
    The query object you get when you call a script through an
    :class:`quma.AsyncCursor`. Its methods await the database.
    """

    async def run(self) -> Self:
        """Execute the query using the DBAPI driver."""
        await self.script.aexecute(
            self.cursor, list(self.args), self.kwargs, self.prepare_params
        )
        self._has_been_executed = True
        self._result_cache = None
        self._rowcount = self.cursor.rowcount
        return self

    async def _fetch(self) -> Sequence[Row]:
        if not self._has_been_executed:
            await self.run()
        if self._result_cache is None:
            try:
                self._result_cache = await self.cursor.fetchall()
            except exc.FetchError as e:
                raise e.error from e
            self._description = self.cursor.description
        return self._result_cache

    async def _len(self) -> int:
        if not self._has_been_executed:
            await self.run()
        length = self._cached_len()
        return len(await self._fetch()) if length is None else length

    # Python can't await in these, so they point to the async methods.
    def __len__(self) -> NoReturn:
        raise TypeError("len() can't await a query. Use await query.count()")

    def __bool__(self) -> NoReturn:
        raise TypeError(
            "An async query has no truth value. Use await query.exists()"
        )

    def __iter__(self) -> NoReturn:
        raise TypeError("Iterate an async query with async for")

    def __getitem__(self, index: int | slice) -> NoReturn:
        raise TypeError(
            "Indexing can't await a query. Use await query.first() "
            "or await query.all()"
        )

    async def __aiter__(self) -> AsyncIterator[Row]:
        for row in await self._fetch():
            yield row

    async def count(self) -> int:
        """Return the length of the result."""
        return await self._len()

    @overload
    async def all(self) -> Sequence[Row]: ...

    @overload
    async def all(
        self, target: type[dict[Any, Any]]
    ) -> list[dict[str, Any]]: ...

    @overload
    async def all(self, target: Target[T]) -> list[T]: ...

    async def all(self, target: Target[Any] | None = None) -> Sequence[Any]:
        """Return a list of all results

        :param target: Map the rows to instances of this class
            (see :doc:`mapping`).
        """
        rows = await self._fetch()
        return map_rows(target, self._description, rows)

    @overload
    async def one(self) -> Row: ...

    @overload
    async def one(self, target: type[dict[Any, Any]]) -> dict[str, Any]: ...

    @overload
    async def one(self, target: Target[T]) -> T: ...

    async def one(self, target: Target[Any] | None = None) -> Any:
        """Get exactly one row and check if only one exists,
        otherwise raise an error.

        :param target: Map the row to an instance of this class
            (see :doc:`mapping`).
        """
        if not self._has_been_executed:
            await self.run()
        if self._result_cache is None and self.cursor.has_rowcount:
            # Fails before fetching a large result.
            check_rowcount(self._rowcount)
        rows = await self._fetch()
        check_rowcount(len(rows))
        return map_rows(target, self._description, rows[:1])[0]

    async def value(self, key: int | str = 0) -> Any:
        """Call :func:`one` and return the first column by default.

        :param key: Return the value at ``key``'s position instead
            of the first column."""
        return (await self.one())[key]

    @overload
    async def first(self) -> Row | None: ...

    @overload
    async def first(
        self, target: type[dict[Any, Any]]
    ) -> dict[str, Any] | None: ...

    @overload
    async def first(self, target: Target[T]) -> T | None: ...

    async def first(self, target: Target[Any] | None = None) -> Any:
        """Get exactly one row and return None if there is no
        row present in the result.

        :param target: Map the row to an instance of this class
            (see :doc:`mapping`).
        """
        rows = (await self._fetch())[:1]
        if not rows:
            return None
        return map_rows(target, self._description, rows)[0]

    async def exists(self) -> bool:
        """Return if the query's result has rows."""
        return await self._len() > 0

    def many(self) -> AsyncManyResult:
        """Return an AsyncManyResult object initialized with
        this query object.
        """
        return AsyncManyResult(self)

    @overload
    def unbunch(self, size: int | None = None) -> AsyncIterator[Row]: ...

    @overload
    def unbunch(
        self, size: int | None = None, target: type[dict[Any, Any]] = ...
    ) -> AsyncIterator[dict[str, Any]]: ...

    @overload
    def unbunch(
        self, size: int | None = None, target: Target[T] = ...
    ) -> AsyncIterator[T]: ...

    async def unbunch(
        self, size: int | None = None, target: Target[Any] | None = None
    ) -> AsyncIterator[Any]:
        """Return an async generator that simplifies the use of fetchmany.

        :param size: The number of rows to be fetched per
            fetchmany call. If not given use the default value
            of the driver.
        :param target: Map the rows to instances of this class
            (see :doc:`mapping`).
        """
        size = self.cursor.arraysize if size is None else size
        await self.run()
        description = self.cursor.description
        while True:
            results = await self.cursor.fetchmany(size)
            if not results:
                break
            for row in map_rows(target, description, results):
                yield row
