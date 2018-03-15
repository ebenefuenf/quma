class Connection(object):
    def __init__(self, database, **kwargs):
        self.factory = None
        self.database = database

        self.username = kwargs.pop('username', None)
        self.password = kwargs.pop('password', None)
        self.persist = True if kwargs.pop('persist', '') == 'yes' else False
        self.changeling = True if kwargs.pop('changeling',
                                             '') == 'yes' else False
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
