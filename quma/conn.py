from psycopg2.pool import ThreadedConnectionPool

from .cursor import ChangelingCursor


class Connection(object):
    def __init__(self, database, **kwargs):
        self.user = kwargs.pop('user')
        self.password = kwargs.pop('password')

        self.database = database


class PostgresPool(Connection):
    def __init__(self, database, **kwargs):
        super().__init__(database, **kwargs)

        self.factory = kwargs.pop('factory', ChangelingCursor)

        pool = kwargs.pop('pool', ThreadedConnectionPool)
        host = kwargs.pop('host', 'localhost')
        port = kwargs.pop('port', '5432')
        minconn = kwargs.pop('minconn', 10)
        maxconn = kwargs.pop('maxconn', 10)

        self._pool = pool(minconn,
                          maxconn,
                          database=self.database,
                          user=self.user,
                          password=self.password,
                          host=host,
                          port=port)

    def getconn(self):
        return self._pool.getconn()

    def putconn(self, conn):
        return self._pool.putconn(conn)

    def disconnect(self):
        self._pool.closeall()
        self._pool = None

    def release_connection(self, carrier):
        if hasattr(carrier, '_conn'):
            self._pool.putconn(carrier._conn)
