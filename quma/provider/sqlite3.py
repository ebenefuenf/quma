import sqlite3

from .. import (
    conn,
    errors,
    exc,
)
from ..rows import (
    ChangelingRow,
    Row,
    column_index,
)


def row_factory(row_class):
    last = (None, {})

    def factory(cursor, values):
        nonlocal last
        description, index = last
        # sqlite3 calls this for every row, and building the index would be
        # the larger part of its cost. Reading ``last`` once keeps it atomic.
        if description is not cursor.description:
            index = column_index(cursor.description)
            last = (cursor.description, index)
        return row_class(values, index)

    return factory


class Connection(conn.Connection):
    dialect = "sqlite"
    driver_error = sqlite3.Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        if not self.database:
            raise ValueError("Required database path missing")
        self.has_rowcount = False
        self._init_conn()

    def create_conn(self, **kwargs):
        try:
            conn = sqlite3.connect(database=self.database, **kwargs)
        except sqlite3.Error as e:
            raise errors.connection_error(e, self.dialect) from e
        conn.row_factory = row_factory(
            ChangelingRow if self.changeling else Row
        )
        return self.disable_autocommit(conn)

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.isolation_level = None
        return conn

    def disable_autocommit(self, conn):
        conn.isolation_level = "DEFERRED"
        return conn

    def in_autocommit(self, conn):
        return conn.isolation_level is None

    def in_transaction(self, conn):
        return conn.in_transaction

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except (sqlite3.ProgrammingError, sqlite3.OperationalError) as e:
            raise exc.ConnectionLost(str(e)) from e
