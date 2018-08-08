try:
    import MySQLdb
except ImportError:
    raise ImportError('In order to use quma with MySQL you'
                      'need to install mysqlclient')

from .. import (
    core,
    exc,
)


class Connection(core.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)

        self.hostname = self.url.hostname or 'localhost'
        self.port = self.url.port or 3306
        if kwargs.pop('dict_cursor', False):
            self.cursor_factory = MySQLdb.cursors.DictCursor
        else:
            self.cursor_factory = MySQLdb.cursors.Cursor
        self._init_conn(**kwargs)

    def cursor(self, conn):
        return conn.cursor(self.cursor_factory)

    def create_conn(self):
        return MySQLdb.connect(db=self.database,
                               user=self.username,
                               passwd=self.password,
                               host=self.hostname,
                               port=self.port)

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute('SELECT 1')
        except MySQLdb.OperationalError:
            raise exc.OperationalError
