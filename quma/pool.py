from psycopg2.pool import ThreadedConnectionPool


class Pool(object):
    def __init__(self, database, user=None, password=None, host='localhost',
                 port='5432', minconn=1, maxconn=10):
        self._pool = ThreadedConnectionPool(minconn,
                                            maxconn,
                                            database=database,
                                            user=user,
                                            password=password,
                                            host=host,
                                            port=port)

    def disconnect(self):
        self._pool.closeall()
        self._pool = None

    def release_connection(self, carrier):
        if hasattr(carrier, '_conn'):
            self._pool.putconn(carrier._conn)
