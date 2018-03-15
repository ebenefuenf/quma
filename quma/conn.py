from urllib.parse import (
    parse_qsl,
    urlparse,
)

import sqlite3

try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    pass

from .cursor import (
    PostgresChangelingCursor,
)


class Connection(object):
    def __init__(self, database, **kwargs):
        self.factory = None
        self.database = database

        self.username = kwargs.pop('username', None)
        self.password = kwargs.pop('password', None)
        self.has_rowcount = True

    def _init_conn(self, **kwargs):
        self.persist = True if kwargs.pop('persist', '') == 'true' else False
        self.conn = None
        if self.persist:
            self.conn = self.get()

    def get(self):
        raise NotImplementedError

    def put(self, conn):
        assert self.conn == conn
        if not self.persist and self.conn:
            self.conn.close()
            self.conn = None

    def close(self):
        if self.conn:
            self.conn.close()
        self.conn = None


class SQLite(Connection):
    def __init__(self, database, **kwargs):
        if not database:
            database = ':memory:'
        super().__init__(database, **kwargs)
        self.has_rowcount = False

        self._init_conn(**kwargs)

    def get(self):
        if not self.conn:
            self.conn = sqlite3.connect(database=self.database)
        return self.conn


class Postgres(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self.hostname = kwargs.pop('hostname', 'localhost')
        self.port = kwargs.pop('port', '5432')
        self.factory = PostgresChangelingCursor

        self._init_conn(**kwargs)

    def get(self):
        if not self.conn:
            self.conn = psycopg2.connect(
                database=self.database,
                user=self.username,
                password=self.password,
                host=self.hostname,
                port=self.port,
                cursor_factory=self.factory)
        return self.conn


class PostgresPool(Postgres):
    def __init__(self, database, **kwargs):
        self.pool = kwargs.pop('pool', ThreadedConnectionPool)
        self.minconn = int(kwargs.pop('minconn', 1))
        self.maxconn = int(kwargs.pop('maxconn', 10))

        super().__init__(database, **kwargs)

    def _init_conn(self, **kwargs):
        self.conn = self.pool(self.minconn,
                              self.maxconn,
                              database=self.database,
                              user=self.username,
                              password=self.password,
                              host=self.hostname,
                              port=self.port,
                              cursor_factory=self.factory)

    def get(self):
        return self.conn.getconn()

    def put(self, conn):
        return self.conn.putconn(conn)

    def close(self):
        self.conn.closeall()
        self.conn = None

    def release(self, carrier):
        if hasattr(carrier, '_quma_conn'):
            self.conn.putconn(carrier._quma_conn)
            del carrier._quma_conn


def connect(dburi):
    engine_map = {
        'sqlite': SQLite,
        'postgresql': Postgres,
        'postgresql+pool': PostgresPool,
    }
    url = urlparse(dburi)
    database = url.path[1:]  # remove the leading slash
    if url.query:
        kwargs = dict(parse_qsl(url.query))
    else:
        kwargs = {}
    for attr in ['username', 'password', 'hostname', 'port']:
        value = getattr(url, attr)
        if value:
            kwargs[attr] = value
    return engine_map[url.scheme](database, **kwargs)
