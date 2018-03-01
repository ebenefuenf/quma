import sqlite3

try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    pass

from .cursor import ChangelingCursor


class Connection(object):
    def __init__(self, database, **kwargs):
        self.database = database

        self.user = kwargs.pop('user')
        self.password = kwargs.pop('password')

    def close(self):
        self._conn.close()
        self._conn = None

    def _init_conn(self, **kwargs):
        self.persist = kwargs.pop('persist', False)
        self._conn = None
        if self.persist:
            self._conn = self.get()

    @property
    def is_pool(self):
        return False


class SQLite(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self._init_conn(**kwargs)

    def get(self):
        if self.persist and self._conn:
            return self._conn
        return sqlite3.connect(database=self.database)


class Postgres(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self.host = kwargs.pop('host', 'localhost')
        self.port = kwargs.pop('port', '5432')
        self.factory = kwargs.pop('factory', ChangelingCursor)

        self._init_conn(**kwargs)

    def get(self):
        if self.persist and self._conn:
            return self._conn
        return psycopg2.connect(database=self.database,
                                user=self.user,
                                password=self.password,
                                host=self.host,
                                port=self.port)


class PostgresPool(Postgres):
    def __init__(self, database, **kwargs):
        self.pool = kwargs.pop('pool', ThreadedConnectionPool)
        self.minconn = kwargs.pop('minconn', 10)
        self.maxconn = kwargs.pop('maxconn', 10)

        super().__init__(database, **kwargs)

    def _init_conn(self, **kwargs):
        self._conn = self.pool(self.minconn,
                               self.maxconn,
                               database=self.database,
                               user=self.user,
                               password=self.password,
                               host=self.host,
                               port=self.port)

    def get(self):
        return self._conn.getconn()

    def put(self, conn):
        return self._conn.putconn(conn)

    def close(self):
        self._conn.closeall()
        self._conn = None

    def release(self, carrier):
        if hasattr(carrier, '_quma_conn'):
            self._conn.putconn(carrier._quma_conn)
            del carrier._quma_conn

    @property
    def is_pool(self):
        return True
