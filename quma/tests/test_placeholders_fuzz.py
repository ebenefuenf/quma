"""Fuzz tests: the servers judge where quma puts placeholders.

Hypothesis builds SELECTs from strings, names, comments and placeholders
holding tricky text, together with the row they return. quma converts
them, the driver binds a value that breaks out of any string, name or
comment it lands in, and the server has to return the expected row. quma
may refuse SQL with a PlaceholderError, but never run it differently.

Run more examples with ``--hypothesis-profile=fuzz``.
"""

from typing import NamedTuple

import pytest
from hypothesis import event, given, settings
from hypothesis import strategies as st

from .. import Database, PlaceholderError
from . import util

VALUE = "v'\"`\n*/ -- # $$ %:y"

PIECES = (
    ":x",
    ":y",
    "::x",
    "\\:x",
    ":",
    "'",
    "''",
    '"',
    "`",
    "\\",
    "--",
    "-- ",
    "/*",
    "*/",
    "#",
    "$",
    "$$",
    "$a$",
    "%",
    "!",
    "E'",
    "U&'",
    "\n",
    "\r",
    "\t",
    " ",
    "a",
    "€",
    " ",
)

# A backslash before these characters doesn't change them in escaping
# strings of either server.
PLAIN_ESCAPES = set(":\"'`$#*/-!a ")

PG_GAPS = (
    "\n",
    "\r",
    "\r\n",
    " \n\t",
    "\t-- :x '\n",
    " --\r",
    "\v\n\v",
    "\f\n",
)

MYSQL_GAPS = (" ", "\n", " /* c */ ", "\t# c\n", " -- c\r\n")

MYSQL_MARKERS = (
    *(None,) * 4,
    "/*!",
    "/*!50600",
    "/*!50700",
    "/*!100100",
    "/*M!",
    "/*M!100100",
    "/*M!999999",
)


class Server(NamedTuple):
    version: int
    mariadb: bool


class Mode(NamedTuple):
    backslashes: bool
    ansi_quotes: bool


def text(exclude=(), max_size=6):
    pieces = [piece for piece in PIECES if piece not in exclude]
    return st.lists(st.sampled_from(pieces), max_size=max_size).map("".join)


def doubled(value, quote):
    return quote + value.replace(quote, quote * 2) + quote


@st.composite
def escaped(draw, value, quote):
    chars = []
    for char in value:
        if char == "\\":
            chars.append("\\\\")
        elif char == quote:
            chars.append(draw(st.sampled_from([quote * 2, "\\" + quote])))
        elif char in PLAIN_ESCAPES and draw(st.booleans()):
            chars.append("\\" + char)
        else:
            chars.append(char)
    return quote + "".join(chars) + quote


@st.composite
def pg_string(draw, backslashes):
    kind = draw(
        st.sampled_from(["standard", "escape", "typed", "dollar", "unicode"])
    )
    if kind == "dollar":
        value = draw(text())
        delimiter = "$" + draw(st.sampled_from(["", "a", "q_1", "€"])) + "$"
        if (value + delimiter).find(delimiter) < len(value):
            value = value.replace("$", "")
        return delimiter + value + delimiter, value
    if kind == "unicode" and not backslashes:
        value = draw(text())
        return "U&" + doubled(value.replace("\\", "\\\\"), "'"), value
    prefix = {
        "escape": draw(st.sampled_from(["E", "e"])),
        "typed": "text ",
    }.get(kind, "")
    parts = draw(st.lists(text(), min_size=1, max_size=3))
    sql = prefix
    for i, part in enumerate(parts):
        if i:
            sql += draw(st.sampled_from(PG_GAPS))
        if backslashes or kind == "escape":
            sql += draw(escaped(part, "'"))
        else:
            sql += doubled(part, "'")
    return sql, "".join(parts)


@st.composite
def pg_column(draw, backslashes):
    kind = draw(st.sampled_from(["placeholder", "string", "string", "slice"]))
    if kind == "placeholder":
        placeholders = [":x", "(:x)", ":x::text", "CAST(:x AS text)"]
        return draw(st.sampled_from(placeholders)), VALUE
    if kind == "slice":
        return "(ARRAY['a', 'b', 'c'])[2\\:3]", ["b", "c"]
    sql, value = draw(pg_string(backslashes))
    return sql + draw(st.sampled_from(["", "::text"])), value


@st.composite
def pg_alias(draw, i):
    name = draw(text(exclude=("\n", "\r", "\t"), max_size=4)).strip()
    if not name:
        return f"c{i}", f"c{i}"
    return doubled(name, '"'), name


def pg_noise():
    return st.lists(
        st.one_of(
            st.sampled_from([" ", "\n", "\t", "\r", "\f", "\v"]),
            text(exclude=("\n", "\r")).map(lambda t: f"--{t}\n"),
            text(exclude=("/*", "*/")).map(lambda t: f"/*{t}*/"),
            st.tuples(
                text(exclude=("/*", "*/")), text(exclude=("/*", "*/"))
            ).map(lambda ts: f"/*{ts[0]} /*{ts[1]}*/ */"),
        ),
        max_size=3,
    ).map("".join)


@st.composite
def mysql_string(draw, mode):
    quotes = ["'"] if mode.ansi_quotes else ["'", '"']
    prefix = draw(st.sampled_from(["", "N", "_utf8mb4", "_utf8mb4 "]))
    parts = draw(st.lists(text(), min_size=1, max_size=3))
    sql = prefix
    for i, part in enumerate(parts):
        if i:
            sql += draw(st.sampled_from(MYSQL_GAPS))
        quote = "'" if prefix and not i else draw(st.sampled_from(quotes))
        if mode.backslashes:
            sql += draw(escaped(part, quote))
        else:
            sql += doubled(part, quote)
    return sql, "".join(parts)


@st.composite
def mysql_column(draw, mode):
    if draw(st.booleans()):
        return draw(st.sampled_from([":x", "(:x)", "CONCAT(:x)"])), VALUE
    return draw(mysql_string(mode))


@st.composite
def mysql_alias(draw, i, mode):
    # The server strips spaces around names.
    name = draw(text(exclude=("\n", "\r", "\t"), max_size=4)).strip()
    if not name:
        return f"c{i}", f"c{i}"
    return doubled(
        name, draw(st.sampled_from('`"' if mode.ansi_quotes else "`"))
    ), name


def mysql_noise():
    return st.lists(
        st.one_of(
            st.sampled_from([" ", "\n", "\t", "\r", "\f"]),
            text(exclude=("\n",)).map(lambda t: f"#{t}\n"),
            st.tuples(
                st.sampled_from([" ", "\t", "\x01"]), text(exclude=("\n",))
            ).map(lambda ts: f"--{ts[0]}{ts[1]}\n"),
            text(exclude=("/*", "*/")).map(lambda t: f"/* {t} */"),
        ),
        max_size=3,
    ).map("".join)


def runs(marker, server):
    digits = marker.lstrip("/*M!")
    version = int(digits or 0)
    if "M" in marker:
        return server.mariadb and version <= server.version
    # MariaDB skips comments for MySQL 5.7 and later.
    if server.mariadb and len(digits) == 5 and version >= 50700:
        return False
    return version <= server.version


@st.composite
def select(draw, columns, alias, noise, server=None):
    """A SELECT and the row it returns. With a server, MySQL's executable
    comments may wrap columns."""
    sql, values, names = "SELECT ", [], []
    if server and draw(st.booleans()):
        sql += "/*+ " + draw(text(exclude=("/*", "*/"))) + " */ "
    columns = draw(st.lists(columns, min_size=1, max_size=4))
    for i, (column, value) in enumerate(columns):
        sql_alias, name = draw(alias(i))
        column = (
            draw(noise)
            + column
            + draw(noise)
            + " AS "
            + sql_alias
            + draw(noise)
        )
        last = i == len(columns) - 1
        marker = (
            None
            if last or not server
            else draw(st.sampled_from(MYSQL_MARKERS))
        )
        # Servers end the comments they don't run at a */ in a string.
        if marker not in (None, "/*!") and ("/*" in column or "*/" in column):
            marker = None
        if marker:
            sql += f"{marker} {column}, */"
        else:
            sql += column + ("" if last else ",")
        if marker is None or runs(marker, server):
            values.append(value)
            names.append(name)
    return sql, values, names


def check(db, setup, query):
    sql, values, names = query
    with db.cursor(autocommit=True) as cur:
        cur.execute(setup)
        try:
            row = cur.query(sql, x=VALUE).one()
        except PlaceholderError:
            event("refused")
            return
        assert list(row) == values
        assert [column[0] for column in cur.description] == names


@pytest.fixture(scope="module")
def pgfuzz():
    db = Database(util.PGSQL_URI, persist=True)
    yield db
    db.close()


@pytest.fixture(scope="module")
def myfuzz():
    db = Database(util.MYSQL_URI, persist=True)
    with db.cursor as cur:
        version = cur.query("SELECT VERSION()").value()
    major, minor, patch = version.split("-")[0].split(".")[:3]
    number = int(major) * 10000 + int(minor) * 100 + int(patch)
    yield db, Server(number, "MariaDB" in version)
    db.close()


@pytest.mark.postgres
@pytest.mark.parametrize(
    "backslashes", [False, True], ids=["standard", "backslashes"]
)
@settings(deadline=None)
@given(data=st.data())
def test_postgresql(pgfuzz, backslashes, data):
    query = select(pg_column(backslashes), pg_alias, pg_noise())
    setting = "off" if backslashes else "on"
    check(
        pgfuzz,
        f"SET standard_conforming_strings = {setting}",
        data.draw(query),
    )


@pytest.mark.mysql
@pytest.mark.parametrize(
    "sql_mode",
    [
        "",
        "NO_BACKSLASH_ESCAPES",
        "ANSI_QUOTES",
        "ANSI_QUOTES,NO_BACKSLASH_ESCAPES",
    ],
)
@settings(deadline=None)
@given(data=st.data())
def test_mysql(myfuzz, sql_mode, data):
    db, server = myfuzz
    mode = Mode(
        "NO_BACKSLASH_ESCAPES" not in sql_mode, "ANSI_QUOTES" in sql_mode
    )
    query = select(
        mysql_column(mode),
        lambda i: mysql_alias(i, mode),
        mysql_noise(),
        server,
    )
    check(db, f"SET SESSION sql_mode = '{sql_mode}'", data.draw(query))
