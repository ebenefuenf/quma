from psycopg2.pool import ThreadedConnectionPool
from psycopg2.extras import NamedTupleCursor


class Pool(object):
    def __init__(self, database, user=None, password=None, host='localhost',
                 port='5432', minconn=1, maxconn=10, factory=NamedTupleCursor):
        self.factory = factory
        self._pool = ThreadedConnectionPool(minconn,
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
