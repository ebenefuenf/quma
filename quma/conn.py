from . import exc


class Connection(object):
    def __init__(self, url, **kwargs):
        self.database = url.path[1:]  # remove the leading slash
        self.username = url.username
        self.password = url.password
        self.url = url

        self.factory = None
        self.changeling = kwargs.pop('changeling', False)
        self.persist = kwargs.pop('persist', False)
        self.pessimistic = kwargs.get('pessimistic', False)
        self.has_rowcount = True

    def _init_conn(self, **kwargs):
        if self.persist:
            self.conn = self.create_conn()

    def cursor(self, conn):
        return conn.cursor()

    def get_cursor_attr(self, cursor, key):
        return getattr(cursor, key)

    def create_conn(self):
        raise NotImplementedError

    def get(self):
        if self.persist:
            if self.pessimistic:
                try:
                    self.check()
                except exc.OperationalError:
                    self.conn = self.create_conn()
            return self.conn
        return self.create_conn()

    def put(self, conn):
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
