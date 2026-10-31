import pathlib
from types import SimpleNamespace

import pytest
from hypothesis import settings

from .. import Database
from . import util

# Based on "default": in CI, the loaded "ci" profile runs the same
# examples every time.
settings.register_profile(
    "fuzz", settings.get_profile("default"), max_examples=5000
)


@pytest.fixture
def pgdburl():
    from urllib.parse import urlparse

    return urlparse(util.PGSQL_URI)


@pytest.fixture(scope="session")
def pyformat_sqldirs():
    p = pathlib.Path(__file__).parent / "fixtures" / "scripts" / "pyformat"
    return str(p)


@pytest.fixture(scope="session")
def named_sqldirs():
    p = pathlib.Path(__file__).parent / "fixtures" / "scripts" / "named"
    return str(p)


@pytest.fixture(scope="session")
def qmark_sqldirs():
    return pathlib.Path(__file__).parent / "fixtures" / "scripts" / "qmark"


@pytest.fixture(scope="session")
def qmark_shadow_sqldirs():
    parent = pathlib.Path(__file__).parent
    return [
        parent / "fixtures" / "scripts" / "qmark",
        str(parent / "fixtures" / "scripts" / "qmark_shadow"),
    ]


@pytest.fixture
def db(qmark_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        persist=True,
        sqldirs=qmark_sqldirs,
        changeling=True,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def db_native(qmark_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        persist=True,
        sqldirs=qmark_sqldirs,
        changeling=True,
        placeholders="native",
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbpess(qmark_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        persist=True,
        pessimistic=True,
        sqldirs=qmark_sqldirs,
        changeling=True,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbecho(qmark_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        qmark_sqldirs,
        persist=True,
        changeling=True,
        echo=True,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbcache(qmark_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        qmark_sqldirs,
        persist=True,
        changeling=True,
        cache=True,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture(params=[False, True], ids=["nocache", "cache"])
def dbshadow(request, qmark_shadow_sqldirs):
    db = Database(
        util.SQLITE_MEMORY,
        qmark_shadow_sqldirs,
        persist=True,
        changeling=True,
        cache=request.param,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbfile(qmark_sqldirs):
    util.remove_db(util.SQLITE_FILE)
    db = Database(util.SQLITE_URI, qmark_sqldirs, changeling=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def dbcommit(qmark_sqldirs):
    util.remove_db(util.SQLITE_FILE)
    db = Database(
        util.SQLITE_URI, qmark_sqldirs, contextcommit=True, changeling=True
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    return db


@pytest.fixture
def db_no_changeling(qmark_sqldirs):
    db = Database(util.SQLITE_MEMORY, qmark_sqldirs, persist=True)
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbdictcb(qmark_sqldirs):
    def dict_callback(carrier, params):
        params["name"] = carrier.name
        return params

    db = Database(
        util.SQLITE_MEMORY,
        qmark_sqldirs,
        prepare_params=dict_callback,
        persist=True,
        changeling=True,
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture
def dbseqcb(qmark_sqldirs):
    def sequence_callback(carrier, params):
        params.append(carrier.email)
        return params

    db = Database(
        util.SQLITE_MEMORY,
        qmark_sqldirs,
        prepare_params=sequence_callback,
        persist=True,
        changeling=True,
        placeholders="native",
    )
    db.execute(util.CREATE_USERS)
    db.execute(util.INSERT_USERS)
    yield db
    db.close()


@pytest.fixture(params=["psycopg2", "psycopg"])
def pgdriver(request):
    dbapi = pytest.importorskip(request.param)
    if request.param == "psycopg2":
        connection = dbapi.extensions.connection
    else:
        connection = dbapi.Connection
    return SimpleNamespace(
        name=request.param,
        dbapi=dbapi,
        connection=connection,
        uri=util.pg_uri(request.param),
        pool_uri=util.pg_uri(request.param + "+pool"),
    )


@pytest.fixture
def pgdb(pgdriver, named_sqldirs):
    db = Database(pgdriver.uri, named_sqldirs, changeling=True)
    return db


@pytest.fixture
def pgdb_native(pgdriver, pyformat_sqldirs):
    db = Database(
        pgdriver.uri, pyformat_sqldirs, changeling=True, placeholders="native"
    )
    return db


@pytest.fixture
def pgdb_echo(pgdriver, named_sqldirs):
    db = Database(pgdriver.uri, named_sqldirs, changeling=True, echo=True)
    return db


@pytest.fixture
def pgdb_persist(pgdriver, named_sqldirs):
    db = Database(pgdriver.uri, named_sqldirs, persist=True)
    yield db
    db.close()


@pytest.fixture
def pgpooldb(pgdriver, named_sqldirs):
    db = Database(pgdriver.pool_uri, named_sqldirs, changeling=True)
    yield db
    db.close()


@pytest.fixture
def pgpooldb_echo(pgdriver, named_sqldirs):
    db = Database(pgdriver.pool_uri, named_sqldirs, changeling=True, echo=True)
    yield db
    db.close()


@pytest.fixture
def mydb(named_sqldirs):
    db = Database(util.MYSQL_URI, named_sqldirs, charset="utf8")
    return db


@pytest.fixture
def mydb_native(pyformat_sqldirs):
    db = Database(
        util.MYSQL_URI, pyformat_sqldirs, charset="utf8", placeholders="native"
    )
    return db


@pytest.fixture
def mydb_dict(named_sqldirs):
    db = Database(
        util.MYSQL_URI, named_sqldirs, dict_cursor=True, charset="utf8"
    )
    return db


@pytest.fixture
def mydb_echo(named_sqldirs):
    db = Database(
        util.MYSQL_URI,
        named_sqldirs,
        dict_cursor=True,
        echo=True,
        charset="utf8",
    )
    return db


@pytest.fixture
def mydb_persist(named_sqldirs):
    db = Database(util.MYSQL_URI, named_sqldirs, persist=True, charset="utf8")
    yield db
    db.close()


@pytest.fixture
def mypooldb(named_sqldirs):
    db = Database(util.MYSQL_POOL_URI, named_sqldirs, charset="utf8")
    yield db
    db.close()


@pytest.fixture
def mypooldb_echo(named_sqldirs):
    db = Database(
        util.MYSQL_POOL_URI, named_sqldirs, echo=True, charset="utf8"
    )
    yield db
    db.close()


@pytest.fixture
def mypooldb_dict(named_sqldirs):
    db = Database(
        util.MYSQL_POOL_URI, named_sqldirs, dict_cursor=True, charset="utf8"
    )
    yield db
    db.close()


@pytest.fixture
def carrier():
    return SimpleNamespace(name="User 1", email="user.1@example.com")


@pytest.fixture
def anyio_backend():
    # psycopg's async API runs on asyncio only.
    return "asyncio"
