import pytest

from .. import Database
from . import util
from .test_transaction import (
    DRIVERS,
    prepare,
)

POSTGRES = [
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("psycopg", marks=pytest.mark.postgres),
]
ROW_VALUES = [
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("mysqlclient", marks=pytest.mark.mysql),
]
BY_IDS = "SELECT id FROM users WHERE id IN :ids ORDER BY id"


@pytest.fixture(params=DRIVERS)
def driver(request):
    return request.param


@pytest.fixture
def open_db(driver, named_sqldirs):
    uri = prepare(driver)
    dbs = []

    def create(sqldirs=named_sqldirs, **kwargs):
        dbs.append(Database(uri, sqldirs, **kwargs))
        return dbs[-1]

    yield create
    for db in dbs:
        db.close()


@pytest.fixture
def db(open_db):
    return open_db()


def ids(db, sql, **params):
    with db.cursor as cur:
        return [row[0] for row in cur.query(sql, **params).all()]


@pytest.mark.parametrize(
    "value",
    [[1, 3], (1, 3), {1, 3}, frozenset({1, 3})],
    ids=lambda v: type(v).__name__,
)
def test_collections(db, value):
    assert ids(db, BY_IDS, ids=value) == [1, 3]


def test_one_element(db):
    assert ids(db, BY_IDS, ids=[2]) == [2]


def test_no_match(db):
    assert ids(db, BY_IDS, ids=[97, 98]) == []


def test_not_in(db):
    sql = "SELECT id FROM users WHERE id NOT IN :ids ORDER BY id"
    assert ids(db, sql, ids=[1, 2, 3, 4, 5, 6]) == [7]


def test_strings(db):
    sql = "SELECT id FROM users WHERE name IN :names ORDER BY id"
    assert ids(db, sql, names=["User 1", "User 3"]) == [1, 3]


@pytest.mark.parametrize(
    "value",
    [
        "x' OR '1'='1",
        "x') OR 1=1 -- ",
        "x\\') OR 1=1 -- ",
        "x'); DROP TABLE users; -- ",
        "x:ids__1%(ids__1)s%s",
    ],
)
def test_values_stay_values(db, value):
    sql = "SELECT id FROM users WHERE name IN :names ORDER BY id"
    assert ids(db, sql, names=[value, "User 2"]) == [2]
    assert len(ids(db, "SELECT id FROM users")) == 7


def test_next_to_other_parameters(db):
    sql = (
        "SELECT id FROM users WHERE city = :city AND id IN :ids "
        "AND name LIKE 'User%' ORDER BY id"
    )
    assert ids(db, sql, city="City A", ids=[1, 2, 3]) == [1, 2]


def test_same_list_twice(db):
    sql = (
        "SELECT id FROM users WHERE id IN :ids AND id NOT IN :other "
        "AND id IN :ids ORDER BY id"
    )
    assert ids(db, sql, ids=[1, 2, 3], other=[2]) == [1, 3]


def test_empty_list_raises_before_the_statement(open_db):
    events = []
    db = open_db(on_execute=events.append)
    with db.cursor as cur:
        for value in ([], (), set()):
            with pytest.raises(ValueError, match='"ids" is empty'):
                cur.query(BY_IDS, ids=value).all()
        assert [row[0] for row in cur.query(BY_IDS, ids=[1]).all()] == [1]
    assert len(events) == 1


def test_name_in_use_raises(db):
    with db.cursor as cur:
        with pytest.raises(ValueError, match='"ids__0"'):
            cur.query(BY_IDS, ids=[1], ids__0=2).all()


def test_parentheses_are_not_expanded(db):
    sql = "SELECT id FROM users WHERE id IN (:ids)"
    with db.cursor as cur:
        with pytest.raises(Exception):  # noqa: B017
            cur.query(sql, ids=[1, 2]).all()
        cur.rollback()


@pytest.mark.parametrize("cache", [False, True])
def test_script_with_lists_of_changing_sizes(open_db, tmp_path, cache):
    (tmp_path / "by_ids.sql").write_text(BY_IDS)
    db = open_db(tmp_path, cache=cache)
    with db.cursor as cur:
        for value in ([1], [1, 2], [1], [3, 4, 5], [2]):
            rows = cur.by_ids(ids=value).all()
            assert [row[0] for row in rows] == sorted(value)


def test_template(open_db, tmp_path):
    (tmp_path / "by_ids.msql").write_text(
        "SELECT id FROM users WHERE id IN :ids\n"
        "% if len(ids) > 1:\n"
        "AND id > 1\n"
        "% endif\n"
        "ORDER BY id"
    )
    db = open_db(tmp_path)
    with db.cursor as cur:
        assert [row[0] for row in cur.by_ids(ids=[1]).all()] == [1]
        assert [row[0] for row in cur.by_ids(ids=[1, 2]).all()] == [2]


def test_list_from_prepare_params(open_db):
    db = open_db(prepare_params=lambda carrier, params: {"ids": [1, 2]})
    assert ids(db, BY_IDS) == [1, 2]


def test_stream(db):
    with db.cursor as cur:
        rows = list(cur.query(BY_IDS, ids=[1, 2, 3]).stream(2))
    assert [row[0] for row in rows] == [1, 2, 3]


def test_hook_sees_what_the_driver_received(open_db, driver):
    events = []
    db = open_db(on_execute=events.append)
    assert ids(db, BY_IDS, ids=[1, 2]) == [1, 2]
    [event] = events
    assert event.params == {"ids__0": 1, "ids__1": 2}
    placeholders = (
        "(:ids__0, :ids__1)"
        if driver == "sqlite3"
        else "(%(ids__0)s, %(ids__1)s)"
    )
    assert placeholders in event.sql


def test_echo(open_db, driver, capsys):
    db = open_db(echo=True)
    assert ids(db, BY_IDS, ids=[1, 2]) == [1, 2]
    bound = "(:ids__0, :ids__1)" if driver == "sqlite3" else "(1, 2)"
    assert bound in capsys.readouterr().out


@pytest.mark.parametrize("driver", POSTGRES)
def test_list_elsewhere_stays_an_array(db):
    sql = "SELECT :tags::text[] AS tags"
    assert ids(db, sql, tags=["a", "b"]) == [["a", "b"]]
    sql = "SELECT id FROM users WHERE id = ANY(:ids) ORDER BY id"
    assert ids(db, sql, ids=[1, 2]) == [1, 2]


@pytest.mark.parametrize("driver", POSTGRES)
def test_empty_list_as_an_array(db):
    sql = "SELECT id FROM users WHERE id = ANY(:ids) ORDER BY id"
    assert ids(db, sql, ids=[]) == []
    sql = "SELECT id FROM users WHERE id <> ALL(:ids) ORDER BY id"
    assert len(ids(db, sql, ids=[])) == 7


@pytest.mark.parametrize("driver", POSTGRES)
def test_list_in_and_as_an_array(db):
    sql = (
        "SELECT id FROM users WHERE id IN :ids AND id = ANY(:ids) ORDER BY id"
    )
    assert ids(db, sql, ids=[1, 2]) == [1, 2]


@pytest.mark.parametrize("driver", ROW_VALUES)
def test_row_values(db):
    sql = "SELECT id FROM users WHERE (id, name) IN :pairs ORDER BY id"
    pairs = [(1, "User 1"), (2, "Nobody")]
    assert ids(db, sql, pairs=pairs) == [1]


@pytest.mark.parametrize("driver", ROW_VALUES)
def test_native_placeholders_stay_with_the_driver(open_db):
    db = open_db(placeholders="native")
    sql = "SELECT id FROM users WHERE id IN %(ids)s ORDER BY id"
    assert ids(db, sql, ids=(1, 2)) == [1, 2]
    with db.cursor as cur:
        cur.execute(sql, {"ids": (1, 2)})
        assert [row[0] for row in cur.fetchall()] == [1, 2]


def test_list_is_not_expanded_in_native_mode():
    db = Database(util.SQLITE_MEMORY, placeholders="native")
    with db.cursor as cur:
        with pytest.raises(Exception, match=":ids|near"):
            cur.query("SELECT 1 WHERE 1 IN :ids", ids=[1]).all()
    db.close()
