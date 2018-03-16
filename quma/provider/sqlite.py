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


class SQLite(core.Connection):
    def __init__(self, database, **kwargs):
        if not database:
            database = ':memory:'
        super().__init__(database, **kwargs)
        self.has_rowcount = False

        self._init_conn(**kwargs)

    def cursor(self):
        return self.conn.cursor()

    def get(self):
        if not self.conn:
            self.conn = sqlite3.connect(database=self.database)
            if self.changeling:
                self.conn.row_factory = SQLiteChangelingRow
        return self.conn
