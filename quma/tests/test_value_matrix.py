"""Hostile values, in queries, streams, executemany and native mode, under the
session settings that change how the server reads SQL: a value must come back as
itself or be refused, and never run. The drivers bind on the client, so nothing
else stands between a value and the SQL.

Set QUMA_VALUE_MATRIX=full for all payloads and settings, after changing how
values are sent. It takes about three minutes.
"""

import os
import pathlib

import pytest

from .. import (
    AsyncDatabase,
    Database,
    exc,
)
from . import util

FULL = os.environ.get("QUMA_VALUE_MATRIX") == "full"
SYNTAX_ERRORS = ("42601", 1064)
ASYNCMY_URI = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")


class WithText:
    def __init__(self, text):
        self.text = text

    def __str__(self):
        return self.text


MANY_TEXT = "INSERT INTO {} VALUES (%s)"
MANY_BYTES = "INSERT INTO {} VALUES (%s)"
PAIR = "SELECT :a AS a, :b AS b"
TEXT_PREFIXES = ["", "\\", "€", "ā", "¿", "¥", "表", "功", "\udcbf", "\n"]
BYTE_PREFIXES = [b"", b"\\", b"\xbf", b"\x81", b"\xa5", b"\xac"]
CLOSERS = ["'", "\\'", "')", "'))", "\\"]
if FULL:
    TEXT_PREFIXES += [
        "\\\\", "é", "₩", "‾", "縿", "\ud800", "\0", "\r", "\x1a", '"', "`", "%",
        "%s", "%(v)s", ":v", "’", "＇", "＼", "ʼ",
    ]  # fmt: skip
    BYTE_PREFIXES += [b"\xe2\x82", b"\xff", b"\x00"]
    CLOSERS += ["''", '"']
TAILS = {
    "mysql": (" UNION SELECT 99 #", " UNION SELECT 99, 99 #"),
    "postgresql": ("; SELECT 99 AS a; --", "; SELECT 99 AS a; --"),
}


def text_carriers(text):
    yield "str", text
    yield "tuple", (text,)
    yield "text of an object", WithText(text)
    if FULL:
        yield "nested tuple", ((text,),)
        yield "list", [text]
        yield "set", {text}
        yield "frozenset", frozenset({text})
        yield "dict", {text: text}
        yield "path", pathlib.PurePosixPath(text)


def byte_carriers(raw):
    yield "bytes", raw
    yield "tuple of bytes", (raw,)
    if FULL:
        yield "bytearray", bytearray(raw)
        yield "memoryview", memoryview(raw)
        yield "list of bytes", [raw]


def cases(dialect):
    """Yield how to run a case, a label, SQL, its parameters, and the row it must
    return, if that's known."""
    tail, second = TAILS[dialect]
    for prefix in TEXT_PREFIXES:
        for closer in CLOSERS:
            text = prefix + closer + tail
            yield from values(text, text_carriers(text))
            yield "many", "text", MANY_TEXT, {"v": text}, [text]
    for prefix in BYTE_PREFIXES:
        for closer in CLOSERS:
            raw = prefix + (closer + tail).encode()
            yield from values(raw, byte_carriers(raw))
            yield "many", "bytes", MANY_BYTES, {"v": raw}, [raw]
    # A value that swallows its closing quote lets the next one run.
    for prefix in TEXT_PREFIXES:
        first = prefix + "\\"
        params = {"a": first, "b": second}
        yield "all", "pair", PAIR, params, [first, second]
    for prefix in BYTE_PREFIXES:
        first = prefix + b"\\"
        params = {"a": first, "b": second.encode()}
        yield "all", "bytes pair", PAIR, params, [first, second.encode()]


def values(plain, carriers):
    for name, value in carriers:
        exact = (
            [plain] if name in ("str", "bytes", "text of an object") else None
        )
        yield "all", name, "SELECT :v AS a", {"v": value}, exact
        yield "stream", name, "SELECT :v AS a", {"v": value}, exact
        yield (
            "all",
            name,
            "SELECT 1 AS a WHERE 'x' IN (:v)",
            {"v": value},
            None,
        )
        if isinstance(value, (tuple, list, set, frozenset)):
            yield (
                "all",
                name,
                "SELECT 1 AS a WHERE 'x' IN :v",
                {"v": value},
                None,
            )


def native_cases(dialect):
    for kind, label, sql, params, exact in cases(dialect):
        if kind == "all" and " IN :v" not in sql:
            for name in params:
                sql = sql.replace(f":{name}", f"%({name})s")
            yield kind, label, sql, params, exact


def verdict(label, sql, params, exact, rows=(), error=None, compare=True):
    """Return what went wrong, if anything."""
    where = f"{label} in {sql} with {params!r}"
    if error is not None:
        if getattr(error, "code", None) in SYNTAX_ERRORS:
            return f"the value moved the end of its string: {where}: {error}"
        if isinstance(error, (exc.DatabaseError, exc.APIError)):
            return None
        return f"{type(error).__name__} wasn't translated: {where}: {error}"
    cells = [_plain(cell) for row in rows for cell in row]
    if any(cell in (99, "99", b"99") for cell in cells):
        return f"the value ran as SQL: {where}: {cells}"
    if " IN " in sql:
        return f"the value ran as SQL: {where}: {cells}" if rows else None
    if len(rows) != 1:
        return f"the value ran as SQL: {where}: {cells}"
    if exact is not None and compare and not _same(cells, exact):
        return f"the value changed: {where}: {cells}"
    return None


def _plain(cell):
    return bytes(cell) if isinstance(cell, (memoryview, bytearray)) else cell


def _same(cells, exact):
    # mysqlclient returns a bytes literal as text, if it's valid text.
    return [
        c.encode() if isinstance(c, str) and isinstance(e, bytes) else c
        for c, e in zip(cells, exact, strict=True)
    ] == exact


PG = {"options": "-c standard_conforming_strings=on"}
PG_OFF = {"options": "-c standard_conforming_strings=off"}
ON = "SET standard_conforming_strings = on"
OFF = "SET standard_conforming_strings = off"
NBE = "SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'"
ANSI = "SET SESSION sql_mode = 'ANSI_QUOTES'"
BOTH = "SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES,ANSI_QUOTES'"


def setting(name, options=None, setup=(), compare=False):
    return pytest.param(options or {}, setup, compare, id=name)


PG_SETTINGS = [
    setting("default", compare=True),
    setting("on to off", PG, [OFF], compare=True),
    setting("off", PG_OFF, compare=True),
    setting("off to on", PG_OFF, [ON]),
    setting("client gbk", {"client_encoding": "GBK"}),
    setting("set gbk", setup=["SET client_encoding = 'GBK'"]),
    setting("set sjis", setup=["SET client_encoding = 'SJIS'"]),
]
MYSQL_SETTINGS = [
    setting("default", compare=True),
    setting("no backslash escapes", setup=[NBE], compare=True),
    setting("big5", {"charset": "big5"}),
    setting("gb18030", {"charset": "gb18030"}),
    setting("sjis", {"charset": "sjis"}),
    setting("set gbk", setup=["SET NAMES gbk"]),
    setting("set big5", setup=["SET NAMES big5"]),
    setting("set big5, no backslash escapes", setup=["SET NAMES big5", NBE]),
]
if FULL:
    for charset in (
        "gbk",
        "ujis",
        "cp932",
        "gb2312",
        "euckr",
        "latin1",
        "koi8r",
    ):
        MYSQL_SETTINGS.append(setting(charset, {"charset": charset}))
    for charset in ("sjis", "cp932", "gb18030", "ujis", "euckr", "latin1"):
        MYSQL_SETTINGS.append(
            setting(f"set {charset}", setup=[f"SET NAMES {charset}"])
        )
    for mode in (ANSI, BOTH):
        MYSQL_SETTINGS.append(setting(mode[-11:], setup=[mode], compare=True))
        MYSQL_SETTINGS.append(
            setting(f"gbk, {mode[-11:]}", {"charset": "gbk"}, [mode])
        )
    MYSQL_SETTINGS += [
        setting("latin1, set gbk", {"charset": "latin1"}, ["SET NAMES gbk"]),
        setting("latin1, set sjis", {"charset": "latin1"}, ["SET NAMES sjis"]),
        setting("gbk, set utf8mb4", {"charset": "gbk"}, ["SET NAMES utf8mb4"]),
        setting("client gbk", setup=["SET character_set_client = gbk"]),
    ]
    for start, now in ((PG, ON), (PG_OFF, OFF)):
        for encoding in (
            "BIG5",
            "UHC",
            "GB18030",
            "JOHAB",
            "LATIN1",
            "EUC_JP",
        ):
            name = f"{encoding}, {start['options'][-3:]} to {now[-3:]}"
            PG_SETTINGS.append(
                setting(name, {**start, "client_encoding": encoding}, [now])
            )


def report(failures):
    assert not failures, f"{len(failures)} failures, like\n" + "\n".join(
        failures[:5]
    )


def tables(dialect):
    blob = "BYTEA" if dialect == "postgresql" else "LONGBLOB"
    yield "CREATE TEMPORARY TABLE matrix_text (a TEXT)"
    yield f"CREATE TEMPORARY TABLE matrix_bytes (a {blob})"


def fetch(cur, kind, sql, params):
    if kind == "stream":
        return list(cur.query(sql, **params).stream())
    if kind == "many":
        table = (
            "matrix_bytes" if isinstance(params["v"], bytes) else "matrix_text"
        )
        cur.executemany(sql.format(table), [(params["v"],)])
        return cur.query(f"SELECT a FROM {table}").all()
    return cur.query(sql, **params).all()


async def afetch(cur, kind, sql, params):
    if kind == "stream":
        return [row async for row in cur.query(sql, **params).stream()]
    if kind == "many":
        table = (
            "matrix_bytes" if isinstance(params["v"], bytes) else "matrix_text"
        )
        await cur.executemany(sql.format(table), [(params["v"],)])
        return await cur.query(f"SELECT a FROM {table}").all()
    return await cur.query(sql, **params).all()


def run_sync(cur, dialect, setup, todo, compare, failures):
    """Return False if the connection broke before the end."""
    for statement in [*setup, *tables(dialect)]:
        cur.execute(statement)
    cur.commit()
    for kind, label, sql, params, exact in todo:
        try:
            rows = fetch(cur, kind, sql, params)
        except Exception as e:
            failure = verdict(label, sql, params, exact, error=e)
        else:
            failure = verdict(label, sql, params, exact, rows, None, compare)
        if failure:
            failures.append(failure)
        try:
            cur.rollback()
        except exc.ConnectionLost:
            return False
    return True


async def run_async(cur, dialect, setup, todo, compare, failures):
    """Return False if the connection broke before the end."""
    for statement in [*setup, *tables(dialect)]:
        await cur.execute(statement)
    await cur.commit()
    for kind, label, sql, params, exact in todo:
        try:
            rows = await afetch(cur, kind, sql, params)
        except Exception as e:
            failure = verdict(label, sql, params, exact, error=e)
        else:
            failure = verdict(label, sql, params, exact, rows, None, compare)
        if failure:
            failures.append(failure)
        try:
            await cur.rollback()
        except exc.ConnectionLost:
            return False
    return True


def check_sync(uri, dialect, options, setup, compare, todo=None):
    failures = []
    todo = cases(dialect) if todo is None else todo
    finished = False
    while not finished:
        db = Database(uri, **options)
        with db.cursor as cur:
            finished = run_sync(cur, dialect, setup, todo, compare, failures)
        db.close()
    report(failures)


async def check_async(uri, dialect, options, setup, compare, todo=None):
    failures = []
    todo = cases(dialect) if todo is None else todo
    finished = False
    while not finished:
        db = AsyncDatabase(uri, **options)
        async with db.cursor as cur:
            finished = await run_async(
                cur, dialect, setup, todo, compare, failures
            )
        await db.close()
    report(failures)


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
@pytest.mark.parametrize("options, setup, compare", PG_SETTINGS)
def test_postgres_values_stay_values(driver, options, setup, compare):
    check_sync(util.pg_uri(driver), "postgresql", options, setup, compare)


@pytest.mark.postgres
@pytest.mark.anyio
@pytest.mark.parametrize("options, setup, compare", PG_SETTINGS[:4])
async def test_async_postgres_values_stay_values(options, setup, compare):
    await check_async(
        util.pg_uri("psycopg"), "postgresql", options, setup, compare
    )


@pytest.mark.mysql
@pytest.mark.parametrize("options, setup, compare", MYSQL_SETTINGS)
def test_mysqlclient_values_stay_values(options, setup, compare):
    try:
        check_sync(util.MYSQL_URI, "mysql", options, setup, compare)
    except exc.DatabaseError as e:
        if "nknown character set" not in str(e):
            raise
        pytest.skip(str(e))


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("options, setup, compare", MYSQL_SETTINGS)
async def test_asyncmy_values_stay_values(options, setup, compare):
    try:
        await check_async(ASYNCMY_URI, "mysql", options, setup, compare)
    except exc.DatabaseError as e:
        if "nknown character set" not in str(e):
            raise
        pytest.skip(str(e))


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_postgres_values_stay_values_in_native_mode(driver):
    options = {"placeholders": "native"}
    todo = native_cases("postgresql")
    check_sync(util.pg_uri(driver), "postgresql", options, [], True, todo)


@pytest.mark.mysql
@pytest.mark.parametrize("setup", [[], [NBE]], ids=["default", "nbe"])
def test_mysqlclient_values_stay_values_in_native_mode(setup):
    options = {"placeholders": "native"}
    check_sync(
        util.MYSQL_URI, "mysql", options, setup, True, native_cases("mysql")
    )


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("setup", [[], [NBE]], ids=["default", "nbe"])
async def test_asyncmy_values_stay_values_in_native_mode(setup):
    options = {"placeholders": "native"}
    await check_async(
        ASYNCMY_URI, "mysql", options, setup, True, native_cases("mysql")
    )
