import sqlite3

try:
    import psycopg2
    from psycopg2.pool import ThreadedConnectionPool
except ImportError:
    pass

from .cursor import ChangelingCursor


class Cursor(object):
    def __init__(self, dbapi_cursor):
        d = {key: getattr(dbapi_cursor, key) for key in dir(dbapi_cursor)}
        self.__dict__ = d
        self.has_rowcount = False


class Connection(object):
    def __init__(self, database, **kwargs):
        self.factory = None
        self.database = database

        self.user = kwargs.pop('user', None)
        self.password = kwargs.pop('password', None)

    def _init_conn(self, **kwargs):
        self.persist = kwargs.pop('persist', False)
        self.conn = None
        if self.persist:
            self.conn = self.get()

    def get(self):
        raise NotImplementedError

    def put(self, conn):
        assert self.conn == self.conn
        if not self.persist and self.conn:
            self.conn.close()
            self.conn = None

    def close(self):
        if self.conn:
            self.conn.close()
        self.conn = None

    def cursor(self):
        if not self.conn:
            self.get()
        return Cursor(self.conn.cursor())


class SQLite(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self._init_conn(**kwargs)

    def get(self):
        if not self.conn:
            self.conn = sqlite3.connect(database=self.database)
        return self.conn


class Postgres(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self.host = kwargs.pop('host', 'localhost')
        self.port = kwargs.pop('port', '5432')
        self.factory = kwargs.pop('factory', ChangelingCursor)

        self._init_conn(**kwargs)

    def get(self):
        if not self.conn:
            self.conn = psycopg2.connect(database=self.database,
                                         user=self.user,
                                         password=self.password,
                                         host=self.host,
                                         port=self.port)
        return self.conn

    def cursor(self):
        if not self.conn:
            self.get()
        c = Cursor(self.conn.cursor(cursor_factory=self.conn.factory))
        c.has_rowcount = True
        return c


class PostgresPool(Postgres):
    def __init__(self, database, **kwargs):
        self.pool = kwargs.pop('pool', ThreadedConnectionPool)
        self.minconn = kwargs.pop('minconn', 1)
        self.maxconn = kwargs.pop('maxconn', 10)

        super().__init__(database, **kwargs)

    def _init_conn(self, **kwargs):
        self.conn = self.pool(self.minconn,
                              self.maxconn,
                              database=self.database,
                              user=self.user,
                              password=self.password,
                              host=self.host,
                              port=self.port)

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
