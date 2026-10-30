"""Converts quma's ``:name`` placeholders to the style of the driver.

The drivers bind parameters on the client, so the tokenizers must read
strings, identifiers and comments exactly like the server does: a
placeholder the server sees inside a string would let its value run as
SQL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator
from typing import Literal, NamedTuple

from .exc import PlaceholderError

Placeholders = Literal["named", "native"]

# Literal text, or the text and the name of a placeholder.
Token = tuple[str, str | None]


class Reading(NamedTuple):
    """Session settings that change how the server reads SQL. quma can't
    see them, so it converts SQL only if every reading agrees."""

    # Backslashes escape in standard strings: PostgreSQL's
    # standard_conforming_strings = off, MySQL's default.
    backslashes: bool = False
    # MySQL's ANSI_QUOTES: "..." is a name, not a string.
    ansi_quotes: bool = False
    # The server runs versioned comments: /*!80000 ... */ runs on MySQL
    # 8.0 and later, /*M! ... */ on MariaDB only.
    versioned: bool = True


# What makes a reading differ from the default, and what to write instead.
_CAUSES = {
    ("postgresql", "backslashes"): (
        "standard_conforming_strings = off",
        "Write a string with backslashes as E'...', for example E'C:\\\\'.",
    ),
    ("mysql", "backslashes"): (
        "the sql_mode NO_BACKSLASH_ESCAPES",
        "Write '' for a quote in a string instead of \\'.",
    ),
    ("mysql", "ansi_quotes"): (
        "the sql_mode ANSI_QUOTES",
        'Write "" for a double quote in a string instead of \\", or use '
        "single quotes.",
    ),
    ("mysql", "versioned"): (
        "another server version or type",
        "Keep placeholders out of versioned comments like /*!80000 ... */ "
        "and /*M! ... */, and */ out of strings in them.",
    ),
}

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

_DOUBLE_PLAIN = re.compile(r'(?:[^"]|"")*+(?:"|\Z)')
_DOUBLE_ESCAPED = re.compile(r'(?:[^"\\]|\\[\s\S]|"")*+(?:"|\Z)')

# The server runs /*! ... */ as SQL: a */ in a string or a line comment
# doesn't end it. "--" starts a comment before ASCII whitespace or control
# characters only.
_MYSQL_TOKEN = re.compile(
    rf"""
        (?P<run>[^'"`\#\-/*:\\]++)
      | (?P<string>['"])
      | (?P<quoted>`(?:[^`]|``)*+(?:`|\Z))
      | (?P<comment>\#[^\n]*+|--(?=[\x00-\x20\x7f]|\Z)[^\n]*+)
      | (?P<executable>/\*(?:[Mm]!|!)\d*+)
      | (?P<block>/\*[\s\S]*?(?:\*/|\Z))
      | (?P<end>\*/)
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

_VERSIONED = re.compile(r"/\*(?:!\d|[Mm]!)")

_NATIVE = re.compile(r"%\([^()]*\)s|%%")


def convert(sql: str, dialect: str) -> str:
    """Return ``sql`` with its ``:name`` placeholders in the driver's
    style: ``%(name)s`` and every other ``%`` doubled for PostgreSQL and
    MySQL, unchanged for SQLite. ``\\:`` stands for a literal colon.

    Raises :class:`quma.PlaceholderError` if ``sql`` contains a
    ``%(name)s`` placeholder or ``%%``: the script was written for the
    driver, see the ``placeholders`` option of :class:`quma.Database`.
    Also raises it if a setting of the session could change where a
    string ends and so whether a placeholder is in it.
    """
    _check(sql)
    scan = _SCANNERS[dialect]
    pyformat = dialect != "sqlite"
    default, *others = _readings(sql, dialect)
    converted = _render(scan(sql, default), pyformat)
    for reading in others:
        other = _render(scan(sql, reading), pyformat)
        if other != converted:
            raise _ambiguous(sql, converted, other, dialect, default, reading)
    return converted


def _readings(sql: str, dialect: str) -> list[Reading]:
    # Without a backslash, the readings don't differ.
    if dialect == "postgresql":
        readings = [Reading()]
        if "\\" in sql:
            readings.append(Reading(backslashes=True))
    elif dialect == "mysql":
        quoting = [Reading(backslashes=True)]
        if "\\" in sql:
            quoting.append(Reading(backslashes=True, ansi_quotes=True))
            quoting.append(Reading())
        readings = list(quoting)
        if _VERSIONED.search(sql):
            readings += [
                reading._replace(versioned=False) for reading in quoting
            ]
    else:
        readings = [Reading()]
    return readings


def _render(tokens: Iterator[Token], pyformat: bool) -> str:
    parts = []
    for text, name in tokens:
        if name is None:
            parts.append(text.replace("%", "%%") if pyformat else text)
        else:
            parts.append(f"%({name})s" if pyformat else text)
    return "".join(parts)


def _ambiguous(
    sql: str,
    converted: str,
    other: str,
    dialect: str,
    default: Reading,
    reading: Reading,
) -> PlaceholderError:
    field = next(
        field
        for field in Reading._fields
        if getattr(reading, field) != getattr(default, field)
    )
    cause, hint = _CAUSES[dialect, field]
    index = next(
        (
            i
            for i, (a, b) in enumerate(zip(converted, other, strict=False))
            if a != b
        ),
        min(len(converted), len(other)),
    )
    lineno = converted.count("\n", 0, index) + 1
    line = sql.split("\n")[lineno - 1].strip()
    return PlaceholderError(
        f"Line {lineno} reads differently with {cause}, so quma can't "
        f"tell where its placeholders are: {line}\n{hint} To pass the SQL "
        'to the driver unchanged, create the database with placeholders="native".'
    )


def _postgresql(sql: str, reading: Reading) -> Iterator[Token]:
    plain = _ESCAPED if reading.backslashes else _PLAIN
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
            pos = _pg_string(sql, pos, plain)
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


def _mysql(sql: str, reading: Reading) -> Iterator[Token]:
    single = _ESCAPED if reading.backslashes else _PLAIN
    if reading.backslashes and not reading.ansi_quotes:
        double = _DOUBLE_ESCAPED
    else:
        double = _DOUBLE_PLAIN
    # Open /*! ... */ comments.
    depth = 0
    pos = 0
    while pos < len(sql):
        match = _match(_MYSQL_TOKEN, sql, pos)
        start, pos = match.span()
        kind = match.lastgroup
        if kind == "name":
            yield match[0], match["name"]
            continue
        if kind == "escape":
            yield ":", None
            continue
        if kind == "string":
            body = single if match[0] == "'" else double
            pos = _match(body, sql, pos).end()
        elif kind == "executable":
            if match[0] == "/*!" or reading.versioned:
                depth += 1
            else:
                end = sql.find("*/", pos)
                pos = len(sql) if end == -1 else end + 2
        elif kind == "end" and depth:
            depth -= 1
        yield sql[start:pos], None


def _sqlite(sql: str, reading: Reading) -> Iterator[Token]:
    pos = 0
    while pos < len(sql):
        match = _match(_SQLITE_TOKEN, sql, pos)
        pos = match.end()
        if match.lastgroup == "name":
            yield match[0], match["name"]
        elif match.lastgroup == "escape":
            yield ":", None
        else:
            yield match[0], None


def _match(pattern: re.Pattern[str], sql: str, pos: int) -> re.Match[str]:
    match = pattern.match(sql, pos)
    # Every pattern matches anywhere: one alternative takes any character.
    assert match is not None
    return match


_SCANNERS: dict[str, Callable[[str, Reading], Iterator[Token]]] = {
    "postgresql": _postgresql,
    "mysql": _mysql,
    "sqlite": _sqlite,
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
