import sqlite3

from .. import (
    conn,
    exc,
)


class SQLiteChangelingRow(sqlite3.Row):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0], row['field']) or by attr (row.field).
    """

    def __getattr__(self, attr):
        try:
            return self[attr]
        except IndexError as e:
            msg = 'Row has no field with the name "{}"'.format(attr)
            raise AttributeError(msg) from e


class Connection(conn.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)
        if not self.database:
            raise ValueError('Required database path missing')
        self.has_rowcount = False
        self._init_conn(**kwargs)

    def cursor(self, conn):
        return conn.cursor()

    def create_conn(self):
        conn = sqlite3.connect(database=self.database)
        if self.changeling:
            conn.row_factory = SQLiteChangelingRow
        return self.disable_autocommit(conn)

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.isolation_level = None
        return conn

    def disable_autocommit(self, conn):
        conn.isolation_level = 'DEFERRED'
        return conn

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute('SELECT 1')
        except sqlite3.ProgrammingError:
            raise exc.OperationalError
        except sqlite3.OperationalError:
            raise exc.OperationalError
