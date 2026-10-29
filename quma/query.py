from __future__ import annotations

from collections.abc import (
    Iterator,
    Sequence,
)
from typing import (
    TYPE_CHECKING,
    Any,
    Self,
    overload,
)

from . import (
    exc,
    mapping,
)
from .conn import Row
from .mapping import (
    T,
    Target,
)

if TYPE_CHECKING:
    from .cursor import BaseCursor
    from .script import (
        PrepareParams,
        Script,
    )


def map_rows(
    target: Target[Any] | None,
    description: Sequence[Sequence[Any]] | None,
    rows: Sequence[Row],
) -> Sequence[Any]:
    if target is None:
        return rows
    return mapping.map_rows(target, description, rows)


def check_rowcount(rowcount: int) -> None:
    if rowcount == 0:
        raise exc.DoesNotExistError()
    if rowcount > 1:
        raise exc.MultipleRowsError()


class ManyResult:
    def __init__(self, query: Query) -> None:
        self.query = query
        self.cursor = query.cursor
        self._has_been_executed = False

    def _run(self) -> None:
        self.query.run()
        self._has_been_executed = True

    @overload
    def get(self, size: int | None = None) -> Sequence[Row]: ...

    @overload
    def get(
        self, size: int | None = None, target: type[dict[Any, Any]] = ...
    ) -> list[dict[str, Any]]: ...

    @overload
    def get(
        self, size: int | None = None, target: Target[T] = ...
    ) -> list[T]: ...

    def get(
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
            self._run()
        rows = self.cursor.fetchmany(size)
        return map_rows(target, self.cursor.description, rows)


class BaseQuery:
    def __init__(
        self,
        script: Script,
        cursor: BaseCursor[Any],
        args: Sequence[Any],
        kwargs: dict[str, Any],
        prepare_params: PrepareParams | None,
    ) -> None:
        self.script = script
        self.cursor = cursor
        self.args = args
        self.kwargs = kwargs
        self.prepare_params = prepare_params
        self._has_been_executed = False
        self._result_cache: Sequence[Row] | None = None
        self._description: Sequence[Sequence[Any]] | None = None
        # The cursor's rowcount changes with the next query run on it.
        self._rowcount = -1

    def _cached_len(self) -> int | None:
        if self._result_cache is not None:
            return len(self._result_cache)
        if self.cursor.has_rowcount:
            return self._rowcount
        return None

    def __getattr__(self, key: str) -> Any:
        return getattr(self.cursor, key)


class Query(BaseQuery):
    """
    The query object is the value you get when you run a query,
    i. e. call a :class:`Script` object.
    """

    def run(self) -> Self:
        """Execute the query using the DBAPI driver."""
        self.script.execute(
            self.cursor, list(self.args), self.kwargs, self.prepare_params
        )
        self._has_been_executed = True
        self._result_cache = None
        self._rowcount = self.cursor.rowcount
        return self

    def _fetch(self) -> Sequence[Row]:
        if not self._has_been_executed:
            self.run()
        if self._result_cache is None:
            try:
                self._result_cache = self.cursor.fetchall()
            except exc.FetchError as e:
                raise e.error from e
            self._description = self.cursor.description
        return self._result_cache

    @overload
    def __getitem__(self, index: int) -> Row: ...

    @overload
    def __getitem__(self, index: slice) -> Sequence[Row]: ...

    def __getitem__(self, index: int | slice) -> Row | Sequence[Row]:
        return self._fetch()[index]

    def __iter__(self) -> Iterator[Row]:
        yield from self._fetch()

    def __bool__(self) -> bool:
        return len(self._fetch()) > 0

    def _len(self) -> int:
        if not self._has_been_executed:
            self.run()
        length = self._cached_len()
        return len(self._fetch()) if length is None else length

    def __len__(self) -> int:
        return self._len()

    def count(self) -> int:
        """Return the length of the result."""
        return self._len()

    @overload
    def all(self) -> Sequence[Row]: ...

    @overload
    def all(self, target: type[dict[Any, Any]]) -> list[dict[str, Any]]: ...

    @overload
    def all(self, target: Target[T]) -> list[T]: ...

    def all(self, target: Target[Any] | None = None) -> Sequence[Any]:
        """Return a list of all results

        :param target: Map the rows to instances of this class
            (see :doc:`mapping`).
        """
        rows = self._fetch()
        return map_rows(target, self._description, rows)

    @overload
    def one(self) -> Row: ...

    @overload
    def one(self, target: type[dict[Any, Any]]) -> dict[str, Any]: ...

    @overload
    def one(self, target: Target[T]) -> T: ...

    def one(self, target: Target[Any] | None = None) -> Any:
        """Get exactly one row and check if only one exists,
        otherwise raise an error.

        :param target: Map the row to an instance of this class
            (see :doc:`mapping`).
        """
        if not self._has_been_executed:
            self.run()
        if self._result_cache is None and self.cursor.has_rowcount:
            # Fails before fetching a large result.
            check_rowcount(self._rowcount)
        rows = self._fetch()
        check_rowcount(len(rows))
        return map_rows(target, self._description, rows[:1])[0]

    def value(self, key: int | str = 0) -> Any:
        """Call :func:`one` and return the first column by default.

        :param key: Return the value at ``key``'s position instead
            of the first column."""
        return self.one()[key]

    @overload
    def first(self) -> Row | None: ...

    @overload
    def first(self, target: type[dict[Any, Any]]) -> dict[str, Any] | None: ...

    @overload
    def first(self, target: Target[T]) -> T | None: ...

    def first(self, target: Target[Any] | None = None) -> Any:
        """Get exactly one row and return None if there is no
        row present in the result.

        :param target: Map the row to an instance of this class
            (see :doc:`mapping`).
        """
        rows = self._fetch()[:1]
        if not rows:
            return None
        return map_rows(target, self._description, rows)[0]

    def exists(self) -> bool:
        """Return if the query's result has rows."""
        return self._len() > 0

    def many(self) -> ManyResult:
        """Return a ManyResult object initialized with
        this query object.
        """
        return ManyResult(self)

    @overload
    def unbunch(self, size: int | None = None) -> Iterator[Row]: ...

    @overload
    def unbunch(
        self, size: int | None = None, target: type[dict[Any, Any]] = ...
    ) -> Iterator[dict[str, Any]]: ...

    @overload
    def unbunch(
        self, size: int | None = None, target: Target[T] = ...
    ) -> Iterator[T]: ...

    def unbunch(
        self, size: int | None = None, target: Target[Any] | None = None
    ) -> Iterator[Any]:
        """Return a generator that simplifies the use of fetchmany.

        :param size: The number of rows to be fetched per
            fetchmany call. If not given use the default value
            of the driver.
        :param target: Map the rows to instances of this class
            (see :doc:`mapping`).
        """
        size = self.cursor.arraysize if size is None else size
        self.run()
        description = self.cursor.description
        while True:
            results = self.cursor.fetchmany(size)
            if not results:
                break
            yield from map_rows(target, description, results)
