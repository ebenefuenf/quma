"""What the MySQL drivers do with values, where it would go wrong.

Both bind on the client, and a value of a type they don't know becomes its
``str()``, however that reads. asyncmy also escapes such text with backslashes
whatever the ``sql_mode``, so it could end its string and run as SQL.

In charsets like big5, gbk and sjis, a backslash can be the second byte of a
character. A byte before the backslash that escapes a quote then takes it away,
and the quote ends the string. Escaping can't prevent this reliably: asyncmy
escapes characters, and only then encodes them, ``¥`` becomes a backslash in sjis.
libmariadb 3.4 misses it for big5, libmysqlclient 8.4 for gb18030, and with ``SET
NAMES`` the server reads another charset than asyncmy knows of.

So non-ASCII values don't get a backslash from quma or the driver. A quote can be
doubled, because no charset has 0x27 in a character. A backslash can't be avoided
in a quoted string, unless a hex literal holds the value. ASCII can't be misread.
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


def quoted(raw: bytes, charset: str) -> bytes:
    """Return a string literal for non-ASCII text in ``charset``, which behaves
    the same whether it has quotes or hex digits: also in a JSON column, and when
    it's converted to the charset of a column."""
    if b"\\" in raw:
        return b"_%s X'%s'" % (charset.encode(), raw.hex().encode())
    return b"'%s'" % raw.replace(b"'", b"''")


def binary(raw: bytes) -> bytes:
    return b"_binary X'%s'" % raw.hex().encode()


def is_text(raw: bytes, encoding: str) -> bool:
    """The server refuses a string in a charset that the bytes aren't valid in."""
    try:
        raw.decode(encoding)
    except UnicodeDecodeError:
        return False
    return True


def _joined(value: set[Any] | frozenset[Any]) -> str:
    try:
        return ",".join(value)
    except TypeError as e:
        raise exc.ProgrammingError(
            "Only a set of strings can be a value, for a SET column."
        ) from e
