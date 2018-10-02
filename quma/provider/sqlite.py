import sqlite3

from .. import (
    PLATFORM,
    conn,
    exc,
)


class SQLiteChangelingRow(sqlite3.Row):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0], row['field']) or by attr (row.field).
    """

    def __init__(self, *args, **kwargs):
        super().__setattr__('_overwritten', {})
        if PLATFORM == 'PyPy':
            super().__init__(*args, **kwargs)
        else:
            super().__init__()

    def __getattribute__(self, attr):
        # Lookup overwritten fields
        try:
            return super().__getattribute__('_overwritten')[attr]
        except KeyError:
            pass
        # Lookup fields in the query result
        try:
            return super().__getitem__(attr)
        except IndexError:
            pass
        # Try to return members of sqlite3.Row itself. For example .keys()
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            pass
        # Try to return "hidden" sqlite3.Row members.
        #
        # Example: if there is a field 'keys' in the result
        # row you can't access the original method 'keys' of
        # the DictRow object. If the original name is prefixed
        # with _ the underscore is removed tried again.
        # e. g. row._keys() will be row.keys()
        try:
            if attr.startswith('_'):
                attr = attr[1:]
            else:
                raise AttributeError
            return super().__getattribute__(attr)
        except AttributeError:
            msg = 'Row has no field with the name "{}"'.format(attr)
            raise AttributeError(msg)

    def __setattr__(self, attr, value):
        super().__getattribute__('_overwritten')[attr] = value


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
