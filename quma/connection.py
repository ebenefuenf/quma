import psycopg2


_pool: psycopg2.pool.ThreadedConnectionPool = None


class Connection(object):
    _pool = None

    def __init__(self, database, user=None, password=None, host='localhost',
                 port='5432', minconn=1, maxconn=10):
        self.database = database
        self.user = user
        self.password = password
        self.host = host
        self.port = port
        self.minconn = minconn
        self.maxconn = maxconn

    def connect(self):
        if not self._pool:
            self._pool = psycopg2.pool.ThreadedConnectionPool(
                self.minconn,
                self.maxconn,
                database=self.database,
                user=self.user,
                password=self.password,
                host=self.host,
                port=self.port)

    def disconnect(self):
        if self._pool:
            self._pool.closeall()
            self._pool = None

    def release_connection(self, carrier):
        if hasattr(carrier, '_conn'):
            self._pool.putconn(carrier._conn)
