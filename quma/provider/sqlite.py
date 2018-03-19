import sqlite3

from .. import core


class SQLiteChangelingRow(sqlite3.Row):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0], row['field']) or by attr (row.field).
    """

    def __getattr__(self, attr):
        try:
            return self[attr]
        except IndexError as e:
            msg = f'Row has no field with the name "{attr}"'
            raise AttributeError(msg) from e


class Connection(core.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)
        if not self.database:
            self.database = ':memory:'
        self.has_rowcount = False

        self._init_conn(**kwargs)

    def create_conn(self):
        conn = sqlite3.connect(database=self.database)
        if self.changeling:
            conn.row_factory = SQLiteChangelingRow
        return conn
