"""What the MySQL drivers do with values, where it would go wrong.

Both bind on the client, and a value of a type they don't know becomes its
``str()``, however that reads. asyncmy also escapes such text with backslashes
whatever the ``sql_mode``, so it could end its string and run as SQL.
"""

from __future__ import annotations

import array
from collections.abc import Container
from decimal import Decimal
from typing import Any

from . import exc


def plain(value: Any, encoders: Container[type]) -> Any:
    """Return ``value`` as a type the driver handles correctly: text, bytes, a
    sequence or a type in ``encoders``. A value whose only text is its
    ``repr()`` raises :class:`quma.ProgrammingError`, as it does on PostgreSQL
    and SQLite."""
    if isinstance(value, (str, bytes)):
        return value
    if isinstance(value, (bytearray, memoryview, array.array)):
        return bytes(value)
    if isinstance(value, (set, frozenset)):
        return _joined(value)
    if type(value) in encoders or isinstance(value, (tuple, list)):
        return value
    for number in (int, float, Decimal):
        if isinstance(value, number):
            return number(value)
    if type(value).__str__ is object.__str__:
        raise exc.ProgrammingError(
            f"can't adapt type '{type(value).__name__}'"
        )
    return str(value)


def _joined(value: set[Any] | frozenset[Any]) -> str:
    try:
        return ",".join(value)
    except TypeError as e:
        raise exc.ProgrammingError(
            "Only a set of strings can be a value, for a SET column."
        ) from e
