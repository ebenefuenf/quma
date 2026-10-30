"""Converts quma's ``:name`` placeholders to the style of the driver.

The drivers bind parameters on the client, so the tokenizers must read
strings, identifiers and comments exactly like the server does: a
placeholder the server sees inside a string would let its value run as
SQL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Literal

from .exc import PlaceholderError

Placeholders = Literal["named", "native"]

# Literal text, or the text and the name of a placeholder.
Token = tuple[str, str | None]

_NAME = r"[^\W\d]\w*"

# PostgreSQL counts every non-ASCII character as an identifier character.
_PG_START = r"A-Za-z_\u0080-\U0010ffff"
_PG_CONT = _PG_START + "0-9"

# Identifiers are tokens: an E'...' string or a $tag$ can't start in one.
_PG_TOKEN = re.compile(
    rf"""
        (?P<run>(?:(?![eE]')[{_PG_START}][{_PG_CONT}$]*+|[^'"$:\\/\-{_PG_START}])++)
      | (?P<escaped>[eE]')
      | (?P<string>')
      | (?P<quoted>"(?:[^"]|"")*+(?:"|\Z))
      | (?P<comment>--[^\n\r]*+)
      | (?P<block>/\*)
      | (?P<dollar>\$(?:[{_PG_START}][{_PG_CONT}]*+)?\$)
      | (?P<cast>::)
      | (?P<escape>\\:)
      | :(?P<name>{_NAME})
      | (?P<other>[\s\S])
    """,
    re.VERBOSE,
)

_PLAIN = re.compile(r"(?:[^']|'')*+(?:'|\Z)")
_ESCAPED = re.compile(r"(?:[^'\\]|\\[\s\S]|'')*+(?:'|\Z)")

# Strings separated by whitespace with a newline (and "--" comments) are
# one string, and an E'...' string keeps its escapes in all parts.
_PG_CONTINUE = re.compile(
    r"(?:[ \t\f\v]|--[^\n\r]*+)*+[\n\r](?:[ \t\n\r\f\v]|--[^\n\r]*+[\n\r])*+'"
)

# PostgreSQL's block comments nest.
_COMMENT_MARK = re.compile(r"/\*|\*/")

_MYSQL_TOKEN = re.compile(
    rf"""
        (?P<run>[^'"`\#\-/:\\]++)
      | (?P<string>'(?:[^'\\]|\\[\s\S]|'')*+(?:'|\Z)|"(?:[^"\\]|\\[\s\S]|"")*+(?:"|\Z))
      | (?P<quoted>`(?:[^`]|``)*+(?:`|\Z))
      | (?P<comment>\#[^\n]*+|--(?=\s|\Z)[^\n]*+)
      | (?P<block>/\*[\s\S]*?(?:\*/|\Z))
      | (?P<cast>::)
      | (?P<escape>\\:)
      | :(?P<name>{_NAME})
      | (?P<other>[\s\S])
    """,
    re.VERBOSE,
)

_SQLITE_TOKEN = re.compile(
    rf"""
        (?P<run>[^'"`\[\-/:\\]++)
      | (?P<string>'(?:[^']|'')*+(?:'|\Z))
      | (?P<quoted>"(?:[^"]|"")*+(?:"|\Z)|`(?:[^`]|``)*+(?:`|\Z)|\[[^\]]*+(?:\]|\Z))
      | (?P<comment>--[^\n]*+)
      | (?P<block>/\*[\s\S]*?(?:\*/|\Z))
      | (?P<cast>::)
      | (?P<escape>\\:)
      | :(?P<name>{_NAME})
      | (?P<other>[\s\S])
    """,
    re.VERBOSE,
)

_NATIVE = re.compile(r"%\([^()]*\)s|%%")


def convert(sql: str, dialect: str) -> str:
    """Return ``sql`` with its ``:name`` placeholders in the driver's
    style: ``%(name)s`` and every other ``%`` doubled for PostgreSQL and
    MySQL, unchanged for SQLite. ``\\:`` stands for a literal colon.

    Raises :class:`quma.PlaceholderError` if ``sql`` contains a
    ``%(name)s`` placeholder or ``%%``: the script was written for the
    driver, see the ``placeholders`` option of :class:`quma.Database`.
    """
    _check(sql)
    tokens = _SCANNERS[dialect](sql)
    pyformat = dialect != "sqlite"
    parts = []
    for text, name in tokens:
        if name is None:
            parts.append(text.replace("%", "%%") if pyformat else text)
        else:
            parts.append(f"%({name})s" if pyformat else text)
    return "".join(parts)


def _postgresql(sql: str) -> Iterator[Token]:
    pos = 0
    while pos < len(sql):
        match = _match(_PG_TOKEN, sql, pos)
        start, pos = match.span()
        kind = match.lastgroup
        if kind == "name":
            yield match[0], match["name"]
            continue
        if kind == "escape":
            yield ":", None
            continue
        if kind == "escaped":
            pos = _pg_string(sql, pos, _ESCAPED)
        elif kind == "string":
            pos = _pg_string(sql, pos, _PLAIN)
        elif kind == "block":
            pos = _comment_end(sql, pos)
        elif kind == "dollar":
            close = sql.find(match[0], pos)
            pos = len(sql) if close == -1 else close + len(match[0])
        yield sql[start:pos], None


def _pg_string(sql: str, pos: int, body: re.Pattern[str]) -> int:
    while True:
        pos = _match(body, sql, pos).end()
        more = _PG_CONTINUE.match(sql, pos)
        if more is None:
            return pos
        pos = more.end()


def _comment_end(sql: str, pos: int) -> int:
    depth = 1
    for mark in _COMMENT_MARK.finditer(sql, pos):
        depth += 1 if mark[0] == "/*" else -1
        if depth == 0:
            return mark.end()
    return len(sql)


def _scanner(token: re.Pattern[str]) -> Callable[[str], Iterator[Token]]:
    def scan(sql: str) -> Iterator[Token]:
        pos = 0
        while pos < len(sql):
            match = _match(token, sql, pos)
            pos = match.end()
            if match.lastgroup == "name":
                yield match[0], match["name"]
            elif match.lastgroup == "escape":
                yield ":", None
            else:
                yield match[0], None

    return scan


def _match(pattern: re.Pattern[str], sql: str, pos: int) -> re.Match[str]:
    match = pattern.match(sql, pos)
    # Every pattern matches anywhere: one alternative takes any character.
    assert match is not None
    return match


_SCANNERS: dict[str, Callable[[str], Iterator[Token]]] = {
    "postgresql": _postgresql,
    "mysql": _scanner(_MYSQL_TOKEN),
    "sqlite": _scanner(_SQLITE_TOKEN),
}


def _check(sql: str) -> None:
    match = _NATIVE.search(sql)
    if match is None:
        return
    lineno = sql.count("\n", 0, match.start()) + 1
    start = sql.rfind("\n", 0, match.start()) + 1
    end = sql.find("\n", match.start())
    line = sql[start : None if end == -1 else end].strip()
    raise PlaceholderError(
        f'Found "{match[0]}" in line {lineno}: {line}\n'
        "quma converts :name placeholders and escapes % itself, so "
        "write :name and a single %. To pass the SQL to the driver "
        'unchanged, create the database with placeholders="native".'
    )
