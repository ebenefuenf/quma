"""What the MySQL drivers do with values, where it would go wrong.

Both bind on the client, and a value of a type they don't know becomes its
``str()``, however that reads. asyncmy also escapes such text with backslashes
whatever the ``sql_mode``, so it could end its string and run as SQL.

In charsets like big5, gbk and sjis, a backslash can be the second byte of a
character. A byte before the backslash that escapes a quote then takes it away,
and the quote ends the string. Escaping can't prevent this reliably: asyncmy
escapes characters, and only then encodes them, ``¥`` becomes a backslash in sjis.
libmariadb 3.4 misses it for big5, libmysqlclient 8.4 for gb18030, and with ``SET
NAMES`` the server reads another charset than asyncmy knows of. A hex literal has
no quote or backslash to misread. Without a byte above 127 in it, or a quote or
backslash, a literal can't be misread either, so those stay readable.
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


def hex_text(value: str, encoding: str, charset: str) -> str | None:
    """Return a hex literal for text whose escaping depends on the charset the
    server reads the SQL in, or None if it has no such risk. Like a literal
    with quotes, it's a string in ``charset``."""
    if value.isascii():
        return None
    raw = value.encode(encoding)
    return _hex(raw, charset) if _has_quoting(raw) else None


def hex_bytes(value: bytes, encoding: str, charset: str) -> str | None:
    """Like :func:`hex_text`. A string in ``charset`` can't hold bytes that
    aren't valid in it, the server refuses it, so those become binary."""
    if value.isascii():
        return None
    try:
        value.decode(encoding)
    except UnicodeDecodeError:
        return _hex(value, "binary")
    return _hex(value, charset) if _has_quoting(value) else None


def _has_quoting(raw: bytes) -> bool:
    return b"'" in raw or b"\\" in raw


def _hex(raw: bytes, charset: str) -> str:
    return f"_{charset} X'{raw.hex()}'"


def _joined(value: set[Any] | frozenset[Any]) -> str:
    try:
        return ",".join(value)
    except TypeError as e:
        raise exc.ProgrammingError(
            "Only a set of strings can be a value, for a SET column."
        ) from e
