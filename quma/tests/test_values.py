import array
import collections
import dataclasses
import decimal
import enum
import fractions
import ipaddress
import pathlib
import time
import uuid

import pytest

from .. import (
    AsyncDatabase,
    Database,
    exc,
)
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
