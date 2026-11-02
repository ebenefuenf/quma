"""The rows of all drivers but psycopg2, whose ``DictRow`` they imitate."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any


def column_index(
    description: Iterable[Sequence[Any]] | None,
) -> dict[str, int]:
    return {column[0]: i for i, column in enumerate(description or ())}


class Row(list):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0]) or key (row['field']).
    """

    __slots__ = ("_index",)

    def __init__(self, values, index):
        super().__init__(values)
        object.__setattr__(self, "_index", index)

    def __getitem__(self, x):
        if not isinstance(x, (int, slice)):
            x = self._index[x]
        return super().__getitem__(x)

    def __setitem__(self, x, value):
        if not isinstance(x, (int, slice)):
            x = self._index[x]
        super().__setitem__(x, value)

    def __contains__(self, key):
        return key in self._index

    def __reduce__(self):
        return (self.__class__, (list(self), self._index))

    def keys(self):
        return iter(self._index)

    def values(self):
        return (list.__getitem__(self, i) for i in self._index.values())

    def items(self):
        return (
            (key, list.__getitem__(self, i)) for key, i in self._index.items()
        )

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def copy(self):
        return dict(self.items())


class ChangelingRow(Row):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0]), key (row['field']) or by attr (row.field).
    """

    __slots__ = ()

    def __getattribute__(self, attr):
        # Lookup fields in the query result
        index = object.__getattribute__(self, "_index")
        try:
            return list.__getitem__(self, index[attr])
        except KeyError:
            pass
        # Try to return members of Row itself. For example .count()
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            pass
        # Try to return "hidden" Row members.
        #
        # Example: if there is a field 'count' in the result
        # row you can't access the original method 'count' of
        # the Row object. If the original name is prefixed
        # with _ the underscore is removed tried again.
        # e. g. row._count(value) will be row.count(value)
        try:
            if attr.startswith("_"):
                attr = attr[1:]
            else:
                raise AttributeError
            return super().__getattribute__(attr)
        except AttributeError as e:
            msg = f'Row has no field with the name "{attr}"'
            raise AttributeError(msg) from e

    def __setattr__(self, attr, value):
        index = object.__getattribute__(self, "_index")
        list.__setitem__(self, index[attr], value)
