try:
    import MySQLdb
    from MySQLdb.cursors import (
        Cursor,
        DictCursor,
    )
except ImportError as e:
    raise ImportError(
        "In order to use quma with MySQL you need to install mysqlclient"
    ) from e

from .. import (
    conn,
    exc,
)


class Connection(conn.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 3306
        if kwargs.pop("dict_cursor", False):
            self.cursor_factory = DictCursor
        else:
            self.cursor_factory = Cursor
        self._init_conn()

    def cursor(self, conn):
        return conn.cursor()

    def create_conn(self, **kwargs):
        try:
            conn = MySQLdb.connect(
                db=self.database,
                user=self.username,
                passwd=self.password,
                host=self.hostname,
                port=self.port,
                cursorclass=self.cursor_factory,
                **kwargs,
            )
        except MySQLdb.OperationalError as e:
            raise exc.ConnectionError(e) from e
        return self.disable_autocommit(conn)

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.autocommit(True)
        return conn

    def disable_autocommit(self, conn):
        conn.autocommit(False)
        return conn

    def mogrify(self, cursor, content, params):
        return cursor._executed.decode("utf-8")

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except MySQLdb.OperationalError as e:
            raise exc.OperationalError from e
