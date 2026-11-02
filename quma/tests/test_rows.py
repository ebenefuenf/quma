"""Rows behave the same with every driver."""

import pickle

import pytest

from .. import Database
from ..rows import ChangelingRow, Row, column_index
from . import util

TWO_COLUMNS = "SELECT 1 AS a, 'x' AS b"
SHADOWING = "SELECT 5 AS count"


def check_row(row):
    assert row[0] == 1
    assert row["a"] == 1
    assert row["b"] == "x"
    assert row[-1] == "x"
    assert row[0:1] == [1]
    assert row == [1, "x"]
    assert list(row) == [1, "x"]
    assert len(row) == 2
    a, b = row
    assert (a, b) == (1, "x")
    assert "a" in row
    assert "c" not in row
    assert list(row.keys()) == ["a", "b"]
    assert list(row.values()) == [1, "x"]
    assert list(row.items()) == [("a", 1), ("b", "x")]
    assert row.get("a") == 1
    assert row.get("c", 9) == 9
    assert row.copy() == {"a": 1, "b": "x"}
    assert dict(row) == {"a": 1, "b": "x"}
    with pytest.raises(KeyError):
        row["c"]
    with pytest.raises(IndexError):
        row[2]
    row["a"] = 2
    assert row[0] == 2
    row[0] = 1
    assert row["a"] == 1


def check_plain(row):
    with pytest.raises(AttributeError):
        row.a


def check_changeling(row):
    assert row.a == 1
    row.a = 2
    assert row[0] == row["a"] == row.a == 2
    row.a = 1
    with pytest.raises(AttributeError):
        row.c
    with pytest.raises(KeyError):
        row.c = 1
    assert list(row._keys()) == ["a", "b"]


def check_shadow(row):
    assert row.count == 5
    assert row._count(5) == 1


@pytest.fixture(
    params=[
        "sqlite3",
        pytest.param("psycopg2", marks=pytest.mark.postgres),
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("mysqlclient", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    pytest.importorskip(
        "MySQLdb" if request.param == "mysqlclient" else request.param
    )
    return request.param


@pytest.fixture(params=["plain", "pool"])
def uri(request, driver):
    pool = request.param == "pool"
    if driver == "sqlite3":
        return (
            f"sqlite3+pool:///{util.SQLITE_FILE}" if pool else util.SQLITE_URI
        )
    if driver == "mysqlclient":
        return util.MYSQL_POOL_URI if pool else util.MYSQL_URI
    return util.pg_uri(f"{driver}+pool" if pool else driver)


def test_default_rows(uri):
    db = Database(uri)
    with db.cursor as cur:
        row = cur.query(TWO_COLUMNS).one()
        check_row(row)
        check_plain(row)
    db.close()


def test_changeling_rows(uri):
    db = Database(uri, changeling=True)
    with db.cursor as cur:
        row = cur.query(TWO_COLUMNS).one()
        check_row(row)
        check_changeling(row)
        check_shadow(cur.query(SHADOWING).one())
    db.close()


@pytest.mark.parametrize("changeling", [False, True])
def test_every_way_to_fetch_gives_the_same_rows(uri, changeling):
    db = Database(uri, changeling=changeling)
    check = check_changeling if changeling else check_plain
    with db.cursor as cur:
        query = cur.query(TWO_COLUMNS)
        rows = [
            query.first(),
            query.all()[0],
            query[0],
            next(iter(cur.query(TWO_COLUMNS))),
        ]
        rows += list(cur.query(TWO_COLUMNS).stream())
        cur.execute(TWO_COLUMNS)
        rows.append(cur.fetchone())
        cur.execute(TWO_COLUMNS)
        rows += cur.fetchall()
        cur.execute(TWO_COLUMNS)
        rows += cur.fetchmany(1)
        assert len(rows) == 8
        for row in rows:
            check_row(row)
            check(row)
    db.close()


def test_a_cursor_follows_the_columns_of_each_statement(uri):
    db = Database(uri)
    with db.cursor as cur:
        cur.execute("SELECT 1 AS a")
        assert cur.fetchall()[0]["a"] == 1
        cur.execute("SELECT 2 AS b, 3 AS c")
        row = cur.fetchall()[0]
        assert row["c"] == 3
        assert "a" not in row
    db.close()


def test_last_of_two_columns_with_one_name_wins(uri):
    db = Database(uri)
    with db.cursor as cur:
        row = cur.query("SELECT 1 AS a, 2 AS a").one()
        assert row["a"] == 2
        assert row == [1, 2]
    db.close()


def test_empty_results(uri):
    db = Database(uri)
    with db.cursor as cur:
        cur.execute("SELECT 1 AS a WHERE 1 = 0")
        assert cur.fetchone() is None
        cur.execute("SELECT 1 AS a WHERE 1 = 0")
        assert len(cur.fetchall()) == 0
    db.close()


def test_mapping_works_on_every_row(uri):
    for changeling in (False, True):
        db = Database(uri, changeling=changeling)
        with db.cursor as cur:
            assert cur.query(TWO_COLUMNS).one(dict) == {"a": 1, "b": "x"}
        db.close()


@pytest.mark.parametrize("row_class", [Row, ChangelingRow])
def test_rows_survive_pickling(row_class):
    row = row_class([1, "x"], column_index([("a",), ("b",)]))
    copy = pickle.loads(pickle.dumps(row))
    assert type(copy) is row_class
    assert copy["b"] == "x"
    assert copy == [1, "x"]
