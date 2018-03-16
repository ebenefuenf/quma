class Connection(object):
    def __init__(self, url, **kwargs):
        self.database = url.path[1:]  # remove the leading slash
        self.username = url.username
        self.password = url.password
        self.url = url

        self.factory = None
        self.persist = kwargs.pop('persist', False)
        self.changeling = kwargs.pop('changeling', False)
        self.has_rowcount = True

    def _init_conn(self, **kwargs):
        self.conn = None
        if self.persist:
            self.conn = self.get()

    def cursor(self):
        return self.conn.cursor()

    def get(self):
        raise NotImplementedError

    def put(self, conn):
        assert self.conn == conn
        if not self.persist and self.conn:
            self.conn.close()
            self.conn = None

    def close(self):
        if self.conn:
            self.conn.close()
        self.conn = None
