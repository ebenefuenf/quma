"""What ``cur.name`` means when SQL has the name of something else on the cursor."""

import ast
import warnings
from pathlib import Path

import pytest

from .. import (
    AsyncDatabase,
    Database,
)
from ..aio.cursor import AsyncCursor
from ..cursor import Cursor
from ..database import _TAKEN_ON_CURSORS
from . import util

SYNC_DRIVERS = [
    "sqlite3",
    pytest.param("psycopg2", marks=pytest.mark.postgres),
    pytest.param("psycopg", marks=pytest.mark.postgres),
    pytest.param("mysqlclient", marks=pytest.mark.mysql),
]


@pytest.fixture(params=SYNC_DRIVERS)
def uri(request, tmp_path):
    if request.param == "sqlite3":
        return f"sqlite3:///{tmp_path / 'names.sqlite'}"
    if request.param == "mysqlclient":
        return util.MYSQL_URI
    return util.pg_uri(request.param)


@pytest.fixture(params=[False, True], ids=["uncached", "cached"])
def cache(request):
    return request.param


def directory(tmp_path, name):
    (tmp_path / name).mkdir()
    (tmp_path / name / "one.sql").write_text("SELECT 1 AS a")
    return tmp_path


TAKEN = [
    "transaction",
    "commit",
    "rollback",
    "query",
    "put",
    "close",
    "create_cursor",
    "mogrify",
    "db",
    "conn",
    "raw_conn",
    "execute",
    "fetchall",
    "description",
    "rowcount",
    "arraysize",
    "connection",
    "cursor",
]


@pytest.mark.parametrize("name", TAKEN)
def test_a_taken_directory_name_warns(tmp_path, name):
    with pytest.warns(UserWarning, match=f"cur.{name} is a member"):
        db = Database("sqlite3:///:memory:", directory(tmp_path, name))
    db.close()


@pytest.mark.parametrize("name", ["transaction", "commit"])
def test_a_taken_root_script_name_warns(tmp_path, name):
    (tmp_path / f"{name}.sql").write_text("SELECT 1 AS a")
    with pytest.warns(UserWarning, match=f"cur.{name} is a member"):
        db = Database("sqlite3:///:memory:", tmp_path)
    db.close()


def test_a_taken_name_warns_with_async_too(tmp_path):
    with pytest.warns(UserWarning, match="cur.transaction is a member"):
        AsyncDatabase(
            "aiosqlite:///:memory:", directory(tmp_path, "transaction")
        )


def test_free_names_dont_warn(tmp_path):
    directory(tmp_path, "users")
    (tmp_path / "get_admin.sql").write_text("SELECT 1 AS a")
    (tmp_path / "notes.txt").write_text("commit")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        db = Database("sqlite3:///:memory:", tmp_path)
    db.close()


@pytest.mark.filterwarnings("ignore:cur.transaction is a member")
def test_a_taken_directory_through_the_database(tmp_path, cache):
    db = Database(
        "sqlite3:///:memory:", directory(tmp_path, "transaction"), cache=cache
    )
    with db.cursor as cur:
        assert db.transaction.one(cur).value() == 1
        with cur.transaction():
            assert cur.query("SELECT 2 AS a").value() == 2
    db.close()


@pytest.mark.filterwarnings("ignore:cur.close is a member")
def test_a_name_taken_on_both_through_the_namespaces(tmp_path, cache):
    db = Database(
        "sqlite3:///:memory:", directory(tmp_path, "close"), cache=cache
    )
    with db.cursor as cur:
        assert db.namespaces["close"].one(cur).value() == 1
    db.close()


EXTRAS = [
    "name",
    "copy",
    "stream",
    "index",
    "closed",
    "statusmessage",
    "scrollable",
]


@pytest.mark.parametrize("name", EXTRAS)
def test_a_directory_wins_over_a_driver_attribute(uri, tmp_path, name, cache):
    db = Database(uri, directory(tmp_path, name), cache=cache)
    with db.cursor as cur:
        assert getattr(cur, name).one().value() == 1
    db.close()


@pytest.mark.parametrize("name", EXTRAS)
def test_a_root_script_wins_over_a_driver_attribute(
    uri, tmp_path, name, cache
):
    (tmp_path / f"{name}.sql").write_text("SELECT 1 AS a")
    db = Database(uri, tmp_path, cache=cache)
    with db.cursor as cur:
        assert getattr(cur, name)().value() == 1
    db.close()


@pytest.mark.postgres
def test_driver_attributes_without_such_sql(tmp_path):
    directory(tmp_path, "users")
    db = Database(util.pg_uri("psycopg2"), tmp_path)
    with db.cursor as cur:
        cur.execute("SELECT 1 AS a")
        assert cur.statusmessage == "SELECT 1"
        assert cur.users.one().value() == 1
    db.close()


@pytest.mark.postgres
def test_the_driver_attribute_stays_on_the_raw_cursor(tmp_path):
    directory(tmp_path, "statusmessage")
    db = Database(util.pg_uri("psycopg2"), tmp_path)
    with db.cursor as cur:
        cur.execute("SELECT 1 AS a")
        assert cur.raw_cursor is not None
        assert cur.raw_cursor.statusmessage == "SELECT 1"
    db.close()


def test_a_missing_name_raises_attribute_error(tmp_path):
    directory(tmp_path, "users")
    db = Database("sqlite3:///:memory:", tmp_path)
    with db.cursor as cur:
        with pytest.raises(AttributeError, match='"nothing" not found'):
            cur.nothing
    db.close()


def test_a_script_shadowed_by_a_method_keeps_its_underscore(tmp_path, cache):
    (tmp_path / "users").mkdir()
    (tmp_path / "users" / "__init__.py").write_text(
        "from quma import Namespace\n\n\n"
        "class Users(Namespace):\n"
        "    def all(self, cur):\n"
        "        return 'method'\n"
    )
    (tmp_path / "users" / "all.sql").write_text("SELECT 1 AS a")
    (tmp_path / "users" / "cache.sql").write_text("SELECT 2 AS a")
    db = Database("sqlite3:///:memory:", tmp_path, cache=cache)
    with db.cursor as cur:
        assert cur.users.all() == "method"
        assert cur.users._all().value() == 1
        assert cur.users._all.script.name == "users/all"
        assert cur.users._cache().value() == 2
        with pytest.raises(AttributeError):
            cur.users._nothing
    db.close()


# Modules that get a quma cursor. In the providers and pools it's the driver's.
USING_CURSORS = (
    "occupation.py",
    "query.py",
    "script.py",
    "stream.py",
    "transaction.py",
    "aio/occupation.py",
    "aio/query.py",
    "aio/stream.py",
    "aio/transaction.py",
)


def is_cursor(node):
    if isinstance(node, ast.Name):
        return node.id == "cursor"
    return isinstance(node, ast.Attribute) and node.attr == "cursor"


def names_read_on_cursors():
    package = Path(__file__).parent.parent
    for module in USING_CURSORS:
        tree = ast.parse((package / module).read_text())
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and is_cursor(node.value):
                yield node.attr
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "getattr"
                and is_cursor(node.args[0])
                and isinstance(node.args[1], ast.Constant)
            ):
                yield node.args[1].value


def test_sql_can_not_hide_what_quma_reads_on_a_cursor():
    names = set(names_read_on_cursors())
    assert {"description", "rowcount", "executions", "_guarded"} <= names
    hidden = {
        name
        for name in names
        if name not in _TAKEN_ON_CURSORS
        and not hasattr(Cursor, name)
        and not hasattr(AsyncCursor, name)
    }
    assert not hidden
