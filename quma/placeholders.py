"""Converts quma's ``:name`` placeholders to the style of the driver."""

from __future__ import annotations

import re

from .exc import PlaceholderError

# Strings, quoted identifiers and comments are copied unchanged. The
# drivers' formatting isn't SQL-aware, so "%" is doubled in them too.
_SKIP = {
    "postgresql": r"""
        (?<![\w$])[eE]'(?:[^'\\]|\\[\s\S]|'')*(?:'|\Z)
      | '(?:[^']|'')*(?:'|\Z)
      | "(?:[^"]|"")*(?:"|\Z)
      | --[^\n]*
      | (?<![\w$])(?P<tag>\$(?:[^\W\d]\w*)?\$)[\s\S]*?(?:(?P=tag)|\Z)
    """,
    "mysql": r"""
        '(?:[^'\\]|\\[\s\S]|'')*(?:'|\Z)
      | "(?:[^"\\]|\\[\s\S]|"")*(?:"|\Z)
      | `(?:[^`]|``)*(?:`|\Z)
      | \#[^\n]*
      | --(?=\s|\Z)[^\n]*
      | /\*[\s\S]*?(?:\*/|\Z)
    """,
    "sqlite": r"""
        '(?:[^']|'')*(?:'|\Z)
      | "(?:[^"]|"")*(?:"|\Z)
      | `(?:[^`]|``)*(?:`|\Z)
      | \[[^\]]*(?:\]|\Z)
      | --[^\n]*
      | /\*[\s\S]*?(?:\*/|\Z)
    """,
}

_TOKENS = {
    dialect: re.compile(
        rf"""
            (?P<skip>{skip})
          | (?P<comment>/\*)
          | ::
          | (?P<escape>\\:)
          | :(?P<name>[^\W\d]\w*)
        """,
        re.VERBOSE,
    )
    for dialect, skip in _SKIP.items()
}

# PostgreSQL's block comments nest.
_COMMENT_MARK = re.compile(r"/\*|\*/")

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
    pyformat = dialect != "sqlite"
    token = _TOKENS[dialect]
    parts: list[str] = []

    def literal(text: str) -> None:
        parts.append(text.replace("%", "%%") if pyformat else text)

    pos = 0
    while (match := token.search(sql, pos)) is not None:
        literal(sql[pos : match.start()])
        pos = match.end()
        if match["name"] is not None:
            parts.append(f"%({match['name']})s" if pyformat else match[0])
        elif match["escape"] is not None:
            parts.append(":")
        elif match["comment"] is not None:
            pos = _comment_end(sql, pos)
            literal(sql[match.start() : pos])
        else:
            literal(match[0])
    literal(sql[pos:])
    return "".join(parts)


def _comment_end(sql: str, pos: int) -> int:
    depth = 1
    for mark in _COMMENT_MARK.finditer(sql, pos):
        depth += 1 if mark[0] == "/*" else -1
        if depth == 0:
            return mark.end()
    return len(sql)


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
