from types import SimpleNamespace

import pytest

from .. import AsyncDatabase
from .test_aio_transaction import (
    DRIVERS,
    MY_URI,
    PG_URI,
    prepare,
)

pytestmark = pytest.mark.anyio

BY_IDS = "SELECT id FROM users WHERE id IN :ids ORDER BY id"


@pytest.fixture(params=DRIVERS)
def uri(request):
    return request.param


@pytest.fixture
async def open_db(uri, named_sqldirs):
    prepare(uri)
    dbs = []

    def create(sqldirs=named_sqldirs, **kwargs):
        dbs.append(AsyncDatabase(uri, sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        await db.close()


@pytest.fixture
def db(open_db):
    return open_db()


async def ids(db, sql, **params):
    async with db.cursor as cur:
        return [row[0] for row in await cur.query(sql, **params).all()]


@pytest.mark.parametrize(
    "value",
    [[1, 3], (1, 3), {1, 3}, frozenset({1, 3})],
    ids=lambda v: type(v).__name__,
)
async def test_collections(db, value):
    assert await ids(db, BY_IDS, ids=value) == [1, 3]


async def test_not_in(db):
    sql = "SELECT id FROM users WHERE id NOT IN :ids ORDER BY id"
    assert await ids(db, sql, ids=[1, 2, 3, 4, 5, 6]) == [7]


@pytest.mark.parametrize(
    "value", ["x' OR '1'='1", "x') OR 1=1 -- ", "x\\') OR 1=1 -- "]
)
async def test_values_stay_values(db, value):
    sql = "SELECT id FROM users WHERE name IN :names ORDER BY id"
    assert await ids(db, sql, names=[value, "User 2"]) == [2]


async def test_empty_list_raises_before_the_statement(open_db):
    events = []
    db = open_db(on_execute=events.append)
    async with db.cursor as cur:
        with pytest.raises(ValueError, match='"ids" is empty'):
            await cur.query(BY_IDS, ids=[]).all()
        rows = await cur.query(BY_IDS, ids=[1]).all()
    assert [row[0] for row in rows] == [1]
    assert len(events) == 1


async def test_script_with_lists_of_changing_sizes(open_db, tmp_path):
    (tmp_path / "by_ids.sql").write_text(BY_IDS)
    db = open_db(tmp_path, cache=True)
    async with db.cursor as cur:
        for value in ([1], [1, 2], [1], [3, 4, 5]):
            rows = await cur.by_ids(ids=value).all()
            assert [row[0] for row in rows] == sorted(value)


async def test_stream(db):
    async with db.cursor as cur:
        rows = [
            row async for row in cur.query(BY_IDS, ids=[1, 2, 3]).stream(2)
        ]
    assert [row[0] for row in rows] == [1, 2, 3]


async def test_hook_sees_what_the_driver_received(open_db):
    events = []
    db = open_db(on_execute=events.append)
    assert await ids(db, BY_IDS, ids=[1, 2]) == [1, 2]
    [event] = events
    assert event.params == {"ids__0": 1, "ids__1": 2}
    assert "(%(ids__0)s, %(ids__1)s)" in event.sql


@pytest.mark.postgres
@pytest.mark.parametrize("uri", [PG_URI])
async def test_list_elsewhere_stays_an_array(db):
    sql = "SELECT id FROM users WHERE id = ANY(:ids) ORDER BY id"
    assert await ids(db, sql, ids=[1, 2]) == [1, 2]
    assert await ids(db, sql, ids=[]) == []
    sql = (
        "SELECT id FROM users WHERE id IN :ids AND id = ANY(:ids) ORDER BY id"
    )
    assert await ids(db, sql, ids=[1, 2]) == [1, 2]


@pytest.mark.mysql
@pytest.mark.parametrize("uri", [MY_URI])
async def test_row_values(db):
    sql = "SELECT id FROM users WHERE (id, name) IN :pairs ORDER BY id"
    assert await ids(db, sql, pairs=[(1, "User 1"), (2, "Nobody")]) == [1]


async def test_carrier(db):
    carrier = SimpleNamespace()
    async with db(carrier).cursor as cur:
        rows = await cur.query(BY_IDS, ids=[1, 2]).all()
    await db.release(carrier)
    assert [row[0] for row in rows] == [1, 2]
