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


class Postgres(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self.host = kwargs.pop('host', 'localhost')
        self.port = kwargs.pop('port', '5432')
        self.factory = kwargs.pop('factory', ChangelingCursor)

        self._init_conn(**kwargs)

    def _init_conn(self, **kwargs):
        self.persist = kwargs.pop('persist', False)
        self._conn = None
        if self.persist:
            self._conn = self.get()

    def get(self):
        if self.persist and self._conn:
            return self._conn
        return psycopg2.connect(database=self.database,
                                user=self.user,
                                password=self.password,
                                host=self.host,
                                port=self.port)

    def close(self):
        self._conn.close()
        self._conn = None


class PostgresPool(Postgres):
    def __init__(self, database, **kwargs):
        self.pool = kwargs.pop('pool', ThreadedConnectionPool)
        self.minconn = kwargs.pop('minconn', 10)
        self.maxconn = kwargs.pop('maxconn', 10)

        super().__init__(database, **kwargs)

    def _init_conn(self, **kwargs):
        self._pool = self.pool(self.minconn,
                               self.maxconn,
                               database=self.database,
                               user=self.user,
                               password=self.password,
                               host=self.host,
                               port=self.port)

    def get(self):
        return self._pool.getconn()

    def put(self, conn):
        return self._pool.putconn(conn)

    def close(self):
        self._pool.closeall()
        self._pool = None

    def release(self, carrier):
        if hasattr(carrier, '_quma_conn'):
            self._pool.putconn(carrier._quma_conn)
            del carrier._quma_conn
