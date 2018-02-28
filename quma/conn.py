from psycopg2.pool import ThreadedConnectionPool

from .cursor import ChangelingCursor


class Pool(object):
    def __init__(self, database, user=None, password=None,
                 host='localhost', port='5432', minconn=1,
                 maxconn=10, factory=ChangelingCursor,
                 pool=ThreadedConnectionPool):
        self.factory = factory
        self._pool = pool(minconn,
                          maxconn,
                          database=database,
                          user=user,
                          password=password,
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
