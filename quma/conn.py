from . import exc


class Connection(object):
    """ Abstract base class for DBMS specific connection objects"""

    def __init__(self, url, kwargs):
        # kwargs are the **kwargs passed to the specific provider
        # sub class. They must be passed as regular dict to be
        # able to pop some values which should not be passed
        # to the dbapi driver.
        self.database = url.path[1:]  # remove the leading slash
        self.username = url.username
        self.password = url.password
        self.url = url
        self.factory = None
        self.changeling = kwargs.pop('changeling', False)
        self.persist = kwargs.pop('persist', False)
        self.pessimistic = kwargs.pop('pessimistic', False)
        self.has_rowcount = True
        self.dbapi_kwargs = kwargs

    def _init_conn(self):
        if self.persist:
            self.conn = self.create_conn(**self.dbapi_kwargs)

    def cursor(self, conn):
        return conn.cursor()

    def get_cursor_attr(self, cursor, key):
        return getattr(cursor, key)

    def create_conn(self):
        raise NotImplementedError

    def enable_autocommit_if(self, autocommit, conn):
        raise NotImplementedError

    def disable_autocommit(self, conn):
        raise NotImplementedError

    def get(self, autocommit=False):
        if self.persist:
            if self.pessimistic:
                try:
                    self.check()
                except exc.OperationalError:
                    self.conn = self.create_conn(**self.dbapi_kwargs)
            return self.enable_autocommit_if(autocommit, self.conn)
        return self.enable_autocommit_if(autocommit,
                                         self.create_conn(**self.dbapi_kwargs))

    def put(self, conn):
        conn.rollback()
        self.disable_autocommit(conn)
        if not self.persist:
            conn.close()

    def close(self, conn=None):
        if conn:
            conn.close()
            return
        if not self.persist:
            raise exc.APIError("Don't call the close() method of "
                               "non-persistent connections.")
        if self.conn:
            self.conn.close()
            del self.conn

    def _check(self, conn):
        raise NotImplementedError

    def check(self, conn=None):
        if conn:
            self._check(conn)
            return
        self._check(self.conn)
