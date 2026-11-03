import array
import collections
import contextlib
import dataclasses
import decimal
import enum
import fractions
import ipaddress
import pathlib
import time
import uuid
from typing import Any

import pytest

from .. import (
    AsyncDatabase,
    Database,
    exc,
)
from .. import values as quma_values
from . import util

ASYNCMY_URI = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")


class WithText:
    def __str__(self):
        return "its text"


class Plain:
    pass


@dataclasses.dataclass
class Data:
    a: str = "x"


class Color(enum.Enum):
    RED = "red"


class Level(enum.IntEnum):
    HIGH = 7


class Name(enum.StrEnum):
    A = "a"


class Count(int):
    pass


class Ratio(float):
    pass


class Price(decimal.Decimal):
    pass


REPR_ONLY = [
    pytest.param(complex(1, 2), id="complex"),
    pytest.param({"a": "b"}, id="dict"),
    pytest.param(collections.OrderedDict(a="b"), id="ordereddict"),
    pytest.param(collections.deque(["a"]), id="deque"),
    pytest.param(range(2), id="range"),
    pytest.param({"a": 1}.keys(), id="dict_keys"),
    pytest.param(Plain(), id="object"),
    pytest.param(Data(), id="dataclass"),
    pytest.param(len, id="function"),
    pytest.param(int, id="class"),
    pytest.param({1}, id="set of integers"),
    pytest.param({b"a"}, id="set of bytes"),
]
SAME_ON_BOTH = [
    pytest.param(uuid.UUID(int=1), str(uuid.UUID(int=1)), id="uuid"),
    pytest.param(pathlib.PurePosixPath("a/b"), "a/b", id="path"),
    pytest.param(ipaddress.ip_address("127.0.0.1"), "127.0.0.1", id="ip"),
    pytest.param(WithText(), "its text", id="own text"),
    pytest.param(fractions.Fraction(1, 2), "1/2", id="fraction"),
    pytest.param(Color.RED, "Color.RED", id="enum"),
    pytest.param(Name.A, "a", id="str enum"),
    pytest.param(Level.HIGH, 7, id="int enum"),
    pytest.param(Count(5), 5, id="int subclass"),
    pytest.param(Ratio(1.5), 1.5, id="float subclass"),
    pytest.param(Price("1.5"), decimal.Decimal("1.5"), id="decimal subclass"),
    pytest.param({"a"}, "a", id="set"),
    pytest.param(frozenset({"a"}), "a", id="frozenset"),
    pytest.param(["a"], "a", id="list"),
    pytest.param(("a",), "a", id="tuple"),
    pytest.param((("a",),), "a", id="nested tuple"),
]
AS_BYTES = [
    pytest.param(bytearray(b"\xffa"), id="bytearray"),
    pytest.param(memoryview(b"\xffa"), id="memoryview"),
    pytest.param(array.array("B", [255, 97]), id="array"),
]
BYTES_IN_A_BLOB = b"\xffa"
BLOB = "CREATE TEMPORARY TABLE blobs (a BLOB)"


@pytest.fixture
def mysqlclient():
    db = Database(util.MYSQL_URI)
    with db.cursor as cur:
        yield cur
    db.close()


@pytest.fixture
async def asyncmy():
    db = AsyncDatabase(ASYNCMY_URI)
    async with db.cursor as cur:
        yield cur
    await db.close()


@pytest.mark.mysql
@pytest.mark.parametrize("value", REPR_ONLY)
def test_mysqlclient_refuses_values_without_text(mysqlclient, value):
    with pytest.raises(exc.ProgrammingError):
        mysqlclient.query("SELECT :v AS a", v=value).all()


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("value", REPR_ONLY)
async def test_asyncmy_refuses_values_without_text(asyncmy, value):
    with pytest.raises(exc.ProgrammingError):
        await asyncmy.query("SELECT :v AS a", v=value).all()


@pytest.mark.mysql
@pytest.mark.parametrize("value, expected", SAME_ON_BOTH)
def test_mysqlclient_values(mysqlclient, value, expected):
    assert mysqlclient.query("SELECT :v AS a", v=value).value() == expected


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("value, expected", SAME_ON_BOTH)
async def test_asyncmy_values(asyncmy, value, expected):
    assert await asyncmy.query("SELECT :v AS a", v=value).value() == expected


@pytest.mark.mysql
@pytest.mark.parametrize("value", AS_BYTES)
def test_mysqlclient_stores_byte_buffers_as_bytes(mysqlclient, value):
    mysqlclient.execute(BLOB)
    mysqlclient.query("INSERT INTO blobs VALUES (:v)", v=value).run()
    assert mysqlclient.query("SELECT a FROM blobs").value() == BYTES_IN_A_BLOB


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("value", AS_BYTES)
async def test_asyncmy_stores_byte_buffers_as_bytes(asyncmy, value):
    await asyncmy.execute(BLOB)
    await asyncmy.query("INSERT INTO blobs VALUES (:v)", v=value).run()
    assert (
        await asyncmy.query("SELECT a FROM blobs").value() == BYTES_IN_A_BLOB
    )


@pytest.mark.mysql
@pytest.mark.anyio
async def test_asyncmy_struct_time(asyncmy):
    value = time.gmtime(0)
    assert await asyncmy.query("SELECT :v AS a", v=value).value() == (
        "1970-01-01 00:00:00"
    )


@pytest.mark.mysql
@pytest.mark.anyio
async def test_asyncmy_text_of_an_object_stays_a_value(asyncmy):
    class Hostile:
        def __str__(self):
            return "' UNION SELECT 99 #"

    await asyncmy.execute("SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'")
    rows = await asyncmy.query("SELECT :v AS a", v=Hostile()).all()
    assert [list(row) for row in rows] == [["' UNION SELECT 99 #"]]


@pytest.mark.mysql
def test_mysqlclient_custom_encoders_stay():
    def encode(value, encoders):
        return b"'encoded'"

    conv = dict(pytest.importorskip("MySQLdb.converters").conversions)
    conv[Plain] = encode
    db = Database(util.MYSQL_URI, conv=conv)
    with db.cursor as cur:
        assert cur.query("SELECT :v AS a", v=Plain()).value() == "encoded"
    db.close()


# A byte above 127, then a quote: with the charset below, the backslash that
# escapes the quote can be read as the second byte of a character.
BREAKOUTS = [
    pytest.param(
        {"charset": "big5"}, [], b"\xbf' UNION SELECT 99 #", id="big5"
    ),
    pytest.param({"charset": "gbk"}, [], b"\xbf' UNION SELECT 99 #", id="gbk"),
    pytest.param(
        {"charset": "gb18030"}, [], b"\xbf' UNION SELECT 99 #", id="gb18030"
    ),
    pytest.param(
        {"charset": "sjis"}, [], "¥' UNION SELECT 99 #", id="yen in sjis"
    ),
    pytest.param(
        {"charset": "ujis"}, [], "¥' UNION SELECT 99 #", id="yen in ujis"
    ),
    pytest.param({}, ["SET NAMES gbk"], "€' UNION SELECT 99 #", id="set gbk"),
    pytest.param(
        {}, ["SET NAMES big5"], "€' UNION SELECT 99 #", id="set big5"
    ),
    pytest.param(
        {}, ["SET NAMES sjis"], "ā' UNION SELECT 99 #", id="set sjis"
    ),
    pytest.param(
        {},
        ["SET character_set_client = gbk"],
        "€' UNION SELECT 99 #",
        id="client",
    ),
    pytest.param(
        {"charset": "latin1"},
        ["SET NAMES gbk"],
        "¿' UNION SELECT 99 #",
        id="latin1",
    ),
]


def rows_stay_one(rows):
    assert len(rows) == 1
    assert 99 not in rows[0]
    assert "99" not in rows[0]
    assert b"99" not in rows[0]


@pytest.mark.mysql
@pytest.mark.parametrize("options, setup, value", BREAKOUTS)
def test_mysqlclient_value_stays_a_value_in_any_charset(options, setup, value):
    try:
        db = Database(util.MYSQL_URI, **options)
        with db.cursor as cur:
            for statement in setup:
                cur.execute(statement)
            # The driver may not be able to decode the result as it thinks
            # it's encoded. That's an error, not a value that ran as SQL.
            with contextlib.suppress(exc.DataError):
                rows_stay_one(cur.query("SELECT :v AS a", v=value).all())
        db.close()
    except exc.ConnectionError as e:
        pytest.skip(str(e))


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("options, setup, value", BREAKOUTS)
async def test_asyncmy_value_stays_a_value_in_any_charset(
    options, setup, value
):
    db = AsyncDatabase(ASYNCMY_URI, **options)
    try:
        async with db.cursor as cur:
            for statement in setup:
                await cur.execute(statement)
            rows_stay_one(await cur.query("SELECT :v AS a", v=value).all())
    except exc.ConnectionError as e:
        pytest.skip(str(e))
    finally:
        await db.close()


TEXT = "é'\\ü"
COLUMNS = (
    "CREATE TEMPORARY TABLE cols (t TEXT, l TEXT CHARACTER SET latin1,"
    " b LONGBLOB, j JSON)"
)


@pytest.mark.mysql
def test_mysqlclient_hex_literals_behave_like_strings():
    db = Database(util.MYSQL_URI)
    with db.cursor as cur:
        assert cur.query("SELECT :v AS a", v=TEXT).value() == TEXT
        assert cur.query("SELECT :v = :w AS a", v=TEXT, w=TEXT).value() == 1
        assert cur.query("SELECT 'é' LIKE :v AS a", v="é''").value() == 0
        cur.execute(COLUMNS)
        cur.query(
            "INSERT INTO cols (t, l, b, j) VALUES (:v, :v, :v, :j)",
            v=TEXT,
            j='{"a": "é\'"}',
        ).run()
        row = cur.query("SELECT t, l, b, j FROM cols").one()
        assert row[0] == TEXT
        assert row[1] == TEXT
        assert row[2] == TEXT.encode()
        assert "é'" in row[3]
    db.close()


@pytest.mark.mysql
@pytest.mark.anyio
async def test_asyncmy_hex_literals_behave_like_strings():
    db = AsyncDatabase(ASYNCMY_URI)
    async with db.cursor as cur:
        assert await cur.query("SELECT :v AS a", v=TEXT).value() == TEXT
        query = cur.query("SELECT :v = :w AS a", v=TEXT, w=TEXT)
        assert await query.value() == 1
        await cur.execute(COLUMNS)
        await cur.query(
            "INSERT INTO cols (t, l, b, j) VALUES (:v, :v, :v, :j)",
            v=TEXT,
            j='{"a": "é\'"}',
        ).run()
        row = await cur.query("SELECT t, l, b, j FROM cols").one()
        assert row[0] == TEXT
        assert row[1] == TEXT
        assert row[2] == TEXT.encode()
        assert "é'" in row[3]
    await db.close()


@pytest.mark.mysql
@pytest.mark.parametrize(
    "value", [b"\xff'\\", b"\xc3\xa9'\\", b"\xff", b"\xc3\xa9", b"plain'"]
)
def test_mysqlclient_bytes_keep_their_value(value):
    db = Database(util.MYSQL_URI)
    with db.cursor as cur:
        cur.execute(BLOB)
        cur.query("INSERT INTO blobs VALUES (:v)", v=value).run()
        assert cur.query("SELECT a FROM blobs").value() == value
    db.close()


@pytest.mark.mysql
def test_mysqlclient_valid_bytes_still_fill_a_json_column():
    value = '{"a": "é\'"}'.encode()
    db = Database(util.MYSQL_URI)
    with db.cursor as cur:
        cur.execute("CREATE TEMPORARY TABLE docs (j JSON)")
        cur.query("INSERT INTO docs VALUES (:v)", v=value).run()
        assert "é'" in cur.query("SELECT j FROM docs").value()
    db.close()


NONCONFORMING: dict[str, Any] = {
    "options": "-c standard_conforming_strings=off"
}
HOSTILE = "\\'; SELECT 99 AS a; --"
TURN_ON = "SET standard_conforming_strings = on"


@pytest.fixture(params=[False, True], ids=["plain", "changeling"])
def nonconforming(request):
    db = Database(
        util.pg_uri("psycopg2"), changeling=request.param, **NONCONFORMING
    )
    with db.cursor as cur:
        yield cur
    db.close()


@pytest.mark.postgres
def test_psycopg2_refuses_values_after_the_setting_went_on(nonconforming):
    nonconforming.execute(TURN_ON)
    query = nonconforming.query("SELECT :v AS a", v=HOSTILE)
    with pytest.raises(exc.APIError, match="standard_conforming_strings"):
        query.all()
    with pytest.raises(exc.APIError, match="standard_conforming_strings"):
        nonconforming.execute("SELECT %s", (HOSTILE,))
    with pytest.raises(exc.APIError, match="standard_conforming_strings"):
        nonconforming.executemany("SELECT %s", [(HOSTILE,)])
    with pytest.raises(exc.APIError, match="standard_conforming_strings"):
        nonconforming.callproc("length", (HOSTILE,))
    with pytest.raises(exc.APIError, match="standard_conforming_strings"):
        list(nonconforming.query("SELECT :v AS a", v=HOSTILE).stream())


@pytest.mark.postgres
def test_psycopg2_runs_statements_without_values_after_it_went_on(
    nonconforming,
):
    nonconforming.execute(TURN_ON)
    assert nonconforming.query("SELECT 1 AS a").value() == 1


@pytest.mark.postgres
def test_psycopg2_keeps_values_while_the_setting_stays_off(nonconforming):
    query = nonconforming.query("SELECT :v AS a", v=HOSTILE)
    assert [list(row) for row in query.all()] == [[HOSTILE]]


@pytest.mark.postgres
@pytest.mark.parametrize("driver", ["psycopg2", "psycopg"])
def test_values_stay_values_when_the_setting_goes_off(driver):
    db = Database(util.pg_uri(driver))
    with db.cursor as cur:
        cur.execute("SET standard_conforming_strings = off")
        query = cur.query("SELECT :v AS a", v=HOSTILE)
        assert [list(row) for row in query.all()] == [[HOSTILE]]
    db.close()


@pytest.mark.postgres
def test_psycopg_keeps_values_when_the_setting_goes_on():
    db = Database(util.pg_uri("psycopg"), **NONCONFORMING)
    with db.cursor as cur:
        cur.execute(TURN_ON)
        query = cur.query("SELECT :v AS a", v=HOSTILE)
        assert [list(row) for row in query.all()] == [[HOSTILE]]
    db.close()


# Each of these takes another way into the SQL, and must behave the same.
MIXES = [
    pytest.param("l'été", id="quote"),
    pytest.param("C:\\Müller", id="backslash"),
    pytest.param("é'\\ü", id="both"),
    pytest.param("été", id="neither"),
    pytest.param('é\0\n\r\x1a"', id="control characters"),
    pytest.param("plain 'ascii\\", id="ascii"),
]
MIXED_WITH_LITERALS = [
    "SELECT :v = 'x' AS a",
    "SELECT 'x' IN (:v) AS a",
    "SELECT CONCAT(:v, 'x') AS a",
    "SELECT COALESCE(NULL, :v, 'x') AS a",
    "SELECT :v LIKE 'x' AS a",
    "SELECT :v = :v AS a",
]


@pytest.mark.mysql
@pytest.mark.parametrize("value", MIXES)
def test_mysqlclient_values_mix_with_literals(mysqlclient, value):
    assert mysqlclient.query("SELECT :v AS a", v=value).value() == value
    for sql in MIXED_WITH_LITERALS:
        mysqlclient.query(sql, v=value).all()


@pytest.mark.mysql
@pytest.mark.anyio
@pytest.mark.parametrize("value", MIXES)
async def test_asyncmy_values_mix_with_literals(asyncmy, value):
    assert await asyncmy.query("SELECT :v AS a", v=value).value() == value
    for sql in MIXED_WITH_LITERALS:
        await asyncmy.query(sql, v=value).all()


@pytest.mark.mysql
@pytest.mark.anyio
async def test_asyncmy_keeps_the_collation_of_an_init_command():
    command = "SET NAMES utf8mb4 COLLATE utf8mb4_bin"
    db = AsyncDatabase(ASYNCMY_URI, init_command=command)
    async with db.cursor as cur:
        query = cur.query("SELECT @@collation_connection AS a")
        assert await query.value() == "utf8mb4_bin"
    await db.close()


@pytest.mark.mysql
@pytest.mark.anyio
async def test_asyncmy_closes_a_connection_it_cant_decode_for():
    db = AsyncDatabase(ASYNCMY_URI)
    async with db.cursor as cur:
        await cur.execute("SET character_set_results = latin1")
        with pytest.raises(exc.DataError):
            await cur.query("SELECT 'é' AS a").all()
        with pytest.raises(exc.ConnectionLost):
            await cur.query("SELECT 1 AS a").all()
    await db.close()


def test_is_text():
    assert quma_values.is_text("é".encode(), "utf8")
    assert not quma_values.is_text(b"\xff", "utf8")
    assert quma_values.is_text(b"\x83\x5c", "cp932")
    for byte in (b"\x80", b"\xa0", b"\xfd", b"\xfe", b"\xff"):
        assert byte.decode("cp932")
        assert not quma_values.is_text(byte + b"\\", "cp932")
