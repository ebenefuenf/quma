"""Converts quma's ``:name`` placeholders to the style of the driver.

The drivers bind parameters on the client, so the tokenizers must read
strings, identifiers and comments exactly like the server does: a
placeholder the server sees inside a string would let its value run as
SQL.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterator, Mapping
from typing import Any, Literal, NamedTuple

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
    # How the server reads versioned comments like /*!80000 ... */ and
    # /*M! ... */: it runs them as SQL, skips them (one nested comment
    # included), or reads a plain comment, as MySQL does with /*M! ... */.
    versioned: Literal["run", "skip", "plain"] = "run"


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
}

_NAME = r"[^\W\d]\w*"

# PostgreSQL counts every non-ASCII character as an identifier character.
_PG_START = r"A-Za-z_\u0080-\U0010ffff"
_PG_CONT = _PG_START + "0-9"

# Identifiers are tokens: an E'...' string or a $tag$ can't start in one.
_PG_TOKEN = re.compile(
    rf"""
        (?P<run>(?:(?![eE](?:'|:{_NAME}))[{_PG_START}][{_PG_CONT}$]*+|[^'"$:\\/\-{_PG_START}])++)
      | (?P<escaped>[eE]')
      | (?P<escaped_value>[eE](?=:{_NAME}))
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
_PG_GAP = (
    r"(?:[ \t\f\v]|--[^\n\r]*+)*+[\n\r](?:[ \t\n\r\f\v]|--[^\n\r]*+[\n\r])*+"
)
_PG_CONTINUE = re.compile(_PG_GAP + "'")
_PG_CONTINUE_VALUE = re.compile(rf"{_PG_GAP}:{_NAME}")
_NATIVE_AFTER_E = re.compile(r"(?<![\w$])[eE]%(?:s|\([^)]*\)s)")

# PostgreSQL's block comments nest.
_COMMENT_MARK = re.compile(r"/\*|\*/")

_DOUBLE_PLAIN = re.compile(r'(?:[^"]|"")*+(?:"|\Z)')
_DOUBLE_ESCAPED = re.compile(r'(?:[^"\\]|\\[\s\S]|"")*+(?:"|\Z)')

# Every server runs /*! ... */ without a five digit version as SQL: a */
# in a string or a line comment doesn't end it. "--" starts a comment
# before ASCII whitespace or control characters only.
_MYSQL_TOKEN = re.compile(
    rf"""
        (?P<run>[^'"`\#\-/*:\\]++)
      | (?P<string>['"])
      | (?P<quoted>`(?:[^`]|``)*+(?:`|\Z))
      | (?P<comment>\#[^\n]*+|--(?=[\x00-\x20\x7f]|\Z)[^\n]*+)
      | (?P<executable>/\*!(?!\d{{5}}))
      | (?P<versioned>/\*(?:!\d{{5}}|M!))
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

_VERSIONED = re.compile(r"/\*(?:!\d{5}|M!)")

_LISTS = (list, tuple, set, frozenset)

# Non-ASCII characters are identifier characters on every server. The IN is
# spelled out because re.IGNORECASE would also take a dotless i.
_IN = r"(?<![A-Za-z0-9_$.\u0080-\U0010ffff])[Ii][Nn][ \t\n\r\f\v]*"
_IN_NAME = re.compile(rf"{_IN}:({_NAME})")
_AFTER_IN = re.compile(rf"{_IN}\Z")

_NATIVE = re.compile(r"%\([^()]*\)s|%%")


class Converted(NamedTuple):
    sql: str
    # The lists that became a list of placeholders.
    expanded: frozenset[str]
    # The parameters that have a placeholder of their own.
    kept: frozenset[str]


def list_sizes(sql: str, params: Mapping[str, Any]) -> dict[str, int]:
    """The sizes of the lists in ``params`` that may need expanding. The
    text may be in a string or comment: only ``convert()`` can tell."""
    lists = {k: len(v) for k, v in params.items() if isinstance(v, _LISTS)}
    if not lists:
        return {}
    return {
        name: lists[name] for name in _IN_NAME.findall(sql) if name in lists
    }


def spread(params: Mapping[str, Any], converted: Converted) -> dict[str, Any]:
    """Return ``params`` with a parameter per element of the expanded
    lists. A list without a placeholder of its own has to go: MySQL's
    drivers escape every parameter, used or not, and reject lists or sets."""
    result = dict(params)
    for name in converted.expanded:
        for i, value in enumerate(params[name]):
            key = _element(name, i)
            if key in params:
                raise ValueError(
                    f'The parameter "{key}" has the name quma gives an '
                    f'element of the list "{name}". Rename it.'
                )
            result[key] = value
        if name not in converted.kept:
            del result[name]
    return result


def convert(sql: str, dialect: str) -> str:
    """Return ``sql`` with its ``:name`` placeholders in the driver's
    style: ``%(name)s`` and every other ``%`` doubled for PostgreSQL and
    MySQL, unchanged for SQLite. ``\\:`` stands for a literal colon.

    Raises :class:`quma.PlaceholderError` if ``sql`` contains a
    ``%(name)s`` placeholder or ``%%``: the script was written for the
    driver, see the ``placeholders`` option of :class:`quma.Database`.
    Also raises it if a setting of the session could change where a
    string ends and so whether a placeholder is in it, for a PostgreSQL
    placeholder whose value would become part of an ``E'...'`` string, and
    for MySQL SQL with placeholders and versioned comments.
    """
    return convert_lists(sql, dialect, {}).sql


def convert_lists(
    sql: str, dialect: str, sizes: Mapping[str, int]
) -> Converted:
    """Like :func:`convert`, but a placeholder directly after ``IN`` whose
    name is in ``sizes`` becomes a list of that many placeholders. Only the
    placeholders multiply: the driver still binds every value. Raises
    :class:`ValueError` for an empty list there.
    """
    _check(sql)
    scan = _SCANNERS[dialect]
    pyformat = dialect != "sqlite"
    default, *others = _readings(sql, dialect)
    converted = _render(scan(sql, default), pyformat, sizes)
    # One server may run some versioned comments and skip others, which no
    # reading covers, so only SQL that needs no conversion is safe.
    versioned = _VERSIONED.search(sql) if dialect == "mysql" else None
    if versioned and converted.sql != sql.replace("%", "%%"):
        raise _versioned(sql, versioned)
    for reading in others:
        other = _render(scan(sql, reading), pyformat, sizes).sql
        if other != converted.sql:
            if versioned:
                raise _versioned(sql, versioned)
            raise _ambiguous(
                sql, converted.sql, other, dialect, default, reading
            )
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
                reading._replace(versioned=versioned)
                for versioned in ("skip", "plain")
                for reading in quoting
            ]
    else:
        readings = [Reading()]
    return readings


def _render(
    tokens: Iterator[Token], pyformat: bool, sizes: Mapping[str, int]
) -> Converted:
    parts = []
    expanded = set()
    kept = set()
    # A comment or string before the placeholder is a token of its own.
    previous = ""
    for text, name in tokens:
        if name is None:
            parts.append(text.replace("%", "%%") if pyformat else text)
        elif name in sizes and _AFTER_IN.search(previous):
            parts.append(_expanded(name, sizes[name], pyformat))
            expanded.add(name)
        else:
            parts.append(_placeholder(name, pyformat))
            kept.add(name)
        previous = text
    return Converted("".join(parts), frozenset(expanded), frozenset(kept))


def _placeholder(name: str, pyformat: bool) -> str:
    return f"%({name})s" if pyformat else f":{name}"


def _element(name: str, index: int) -> str:
    return f"{name}__{index}"


def _expanded(name: str, size: int, pyformat: bool) -> str:
    if size == 0:
        raise ValueError(
            f'The parameter "{name}" is empty, and IN needs at least one '
            "value, so handle the empty case before the query. On PostgreSQL, "
            f"= ANY(:{name}) and <> ALL(:{name}) work with empty lists."
        )
    elements = (_element(name, i) for i in range(size))
    return f"({', '.join(_placeholder(e, pyformat) for e in elements)})"


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


def _versioned(sql: str, match: re.Match[str]) -> PlaceholderError:
    lineno = sql.count("\n", 0, match.start()) + 1
    line = sql.split("\n")[lineno - 1].strip()
    return PlaceholderError(
        f"Line {lineno} has a versioned comment, and whether the server runs "
        "it depends on its version and type, so quma can't tell where its "
        f"placeholders are: {line}\nWrite no placeholders or \\: in SQL with "
        "comments like /*!80000 ... */ or /*M! ... */. To pass the SQL to the "
        'driver unchanged, create the database with placeholders="native".'
    )


def _escaped_value(sql: str, pos: int) -> PlaceholderError:
    lineno = sql.count("\n", 0, pos) + 1
    line = sql.split("\n")[lineno - 1].strip()
    return PlaceholderError(
        f"Line {lineno} has a placeholder whose value the server would read "
        "as part of an E'...' string, where a backslash in the value can end "
        f"the string and run the rest as SQL: {line}\nWrite || between a "
        "string and the placeholder, or a space if E is a column's name."
    )


def check_native(sql: str) -> None:
    """Refuse a driver placeholder directly after E on PostgreSQL. It can't be
    meant otherwise: the driver fills in any %s, also in a string or comment."""
    # The regular expression alone takes 49 us on 2 KB of SQL.
    if "E%" in sql or "e%" in sql:
        match = _NATIVE_AFTER_E.search(sql)
        if match:
            raise _escaped_value(sql, match.start())


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
        if kind == "escaped_value":
            raise _escaped_value(sql, start)
        if kind == "escaped":
            pos = _pg_string(sql, pos, _ESCAPED)
            if _PG_CONTINUE_VALUE.match(sql, pos):
                raise _escaped_value(sql, pos)
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
        elif kind == "executable" or (
            kind == "versioned" and reading.versioned == "run"
        ):
            depth += 1
        elif kind == "versioned" and reading.versioned == "skip":
            pos = _skipped_end(sql, pos)
        elif kind == "versioned":
            end = sql.find("*/", pos)
            pos = len(sql) if end == -1 else end + 2
        elif kind == "end" and depth:
            depth -= 1
        yield sql[start:pos], None


def _skipped_end(sql: str, pos: int) -> int:
    # In a skipped versioned comment, the server counts nested comments one
    # level deep, also in what would be strings.
    while mark := _COMMENT_MARK.search(sql, pos):
        pos = mark.end()
        if mark[0] == "*/":
            return pos
        end = sql.find("*/", pos)
        if end == -1:
            break
        pos = end + 2
    return len(sql)


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
