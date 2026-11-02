"""Rows behave the same with every async driver."""

import pytest

from .. import AsyncDatabase
from . import util
from .test_rows import (
    SHADOWING,
    TWO_COLUMNS,
    check_changeling,
    check_plain,
    check_row,
    check_shadow,
)

pytestmark = pytest.mark.anyio


@pytest.fixture(
    params=[
        pytest.param("psycopg", marks=pytest.mark.postgres),
        pytest.param("asyncmy", marks=pytest.mark.mysql),
    ]
)
def driver(request):
    pytest.importorskip(request.param)
    return request.param


@pytest.fixture(params=["plain", "pool"])
def uri(request, driver):
    if driver == "psycopg":
        plain = util.pg_uri("psycopg")
    else:
        plain = util.MYSQL_URI.replace("mysqlclient://", "asyncmy://")
    if request.param == "pool":
        return plain.replace("://", "+pool://", 1)
    return plain


async def test_default_rows(uri):
    db = AsyncDatabase(uri)
    async with db.cursor as cur:
        row = await cur.query(TWO_COLUMNS).one()
        check_row(row)
        check_plain(row)
    await db.close()


async def test_changeling_rows(uri):
    db = AsyncDatabase(uri, changeling=True)
    async with db.cursor as cur:
        row = await cur.query(TWO_COLUMNS).one()
        check_row(row)
        check_changeling(row)
        check_shadow(await cur.query(SHADOWING).one())
    await db.close()


@pytest.mark.parametrize("changeling", [False, True])
async def test_every_way_to_fetch_gives_the_same_rows(uri, changeling):
    db = AsyncDatabase(uri, changeling=changeling)
    check = check_changeling if changeling else check_plain
    async with db.cursor as cur:
        rows = [
            await cur.query(TWO_COLUMNS).first(),
            (await cur.query(TWO_COLUMNS).all())[0],
        ]
        async for row in cur.query(TWO_COLUMNS).stream():
            rows.append(row)
        await cur.execute(TWO_COLUMNS)
        rows.append(await cur.fetchone())
        await cur.execute(TWO_COLUMNS)
        rows += await cur.fetchall()
        await cur.execute(TWO_COLUMNS)
        rows += await cur.fetchmany(1)
        assert len(rows) == 6
        for row in rows:
            check_row(row)
            check(row)
    await db.close()


async def test_a_cursor_follows_the_columns_of_each_statement(uri):
    db = AsyncDatabase(uri)
    async with db.cursor as cur:
        await cur.execute("SELECT 1 AS a")
        assert (await cur.fetchall())[0]["a"] == 1
        await cur.execute("SELECT 2 AS b, 3 AS c")
        row = (await cur.fetchall())[0]
        assert row["c"] == 3
        assert "a" not in row
    await db.close()


async def test_mapping_works_on_every_row(uri):
    for changeling in (False, True):
        db = AsyncDatabase(uri, changeling=changeling)
        async with db.cursor as cur:
            assert await cur.query(TWO_COLUMNS).one(dict) == {
                "a": 1,
                "b": "x",
            }
        await db.close()
