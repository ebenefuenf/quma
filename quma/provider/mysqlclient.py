try:
    import MySQLdb
    from MySQLdb.connections import Connection as DriverConnection
    from MySQLdb.cursors import (
        Cursor,
        SSCursor,
    )
except ImportError as e:
    raise ImportError(
        "In order to use quma with MySQL you need to install mysqlclient"
    ) from e

from typing import Any

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

# ER_CANT_CHANGE_TX_CHARACTERISTICS
TRANSACTION_IN_PROGRESS = 1568
UNKNOWN_VARIABLE = 1193
SET_ACCESS_MODE = "SET @@{0} = @@{0}"


class Rows:
    row_class = Row
    _indexed = None
    _index = None

    def _fetch_row(self: Any, size=1):
        rows = super()._fetch_row(size)
        if self._indexed is not self.description:
            self._indexed = self.description
            self._index = column_index(self.description)
        return tuple(self.row_class(row, self._index) for row in rows)


class RowCursor(Rows, Cursor):
    pass


class RowStreamCursor(Rows, SSCursor):
    pass


class ChangelingCursor(RowCursor):
    row_class = ChangelingRow


class ChangelingStreamCursor(RowStreamCursor):
    row_class = ChangelingRow


class EscapingConnection(DriverConnection):
    def literal(self, o):
        # MySQLdb quotes a set without its connection, with backslashes whatever
        # the sql_mode: under NO_BACKSLASH_ESCAPES, a value can end its string.
        if isinstance(o, set):
            o = ",".join(o)
        return super().literal(o)


class Connection(conn.Connection):
    dialect = "mysql"
    driver_error = MySQLdb.Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)
        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 3306
        if self.changeling:
            self.cursor_factory = ChangelingCursor
            self.stream_factory = ChangelingStreamCursor
        else:
            self.cursor_factory = RowCursor
            self.stream_factory = RowStreamCursor
        self._init_conn()

    def cursor(self, conn):
        return conn.cursor()

    def stream_cursor(self, conn):
        return conn.cursor(self.stream_factory)

    def create_conn(self, **kwargs):
        try:
            conn = EscapingConnection(
                db=self.database,
                user=self.username,
                passwd=self.password,
                host=self.hostname,
                port=self.port,
                cursorclass=self.cursor_factory,
                **kwargs,
            )
        except MySQLdb.Error as e:
            raise errors.connection_error(e, self.dialect) from e
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

    def in_autocommit(self, conn):
        return conn.get_autocommit()

    def in_transaction(self, conn):
        # mysqlclient doesn't expose the server's status. Setting the next
        # transaction's access mode fails in a transaction, and unlike the
        # alternatives it works on MySQL and MariaDB without privileges.
        # Setting it to its value keeps a read-only session read-only.
        cursor = conn.cursor()
        try:
            self._set_access_mode(cursor)
        except MySQLdb.Error as e:
            if e.args[0] == TRANSACTION_IN_PROGRESS:
                return True
            raise
        finally:
            cursor.close()
        return False

    def _set_access_mode(self, cursor):
        try:
            cursor.execute(SET_ACCESS_MODE.format("transaction_read_only"))
        except MySQLdb.Error as e:
            if e.args[0] != UNKNOWN_VARIABLE:
                raise
            # MariaDB before 11.1.
            cursor.execute(SET_ACCESS_MODE.format("tx_read_only"))

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except MySQLdb.OperationalError as e:
            raise exc.ConnectionLost(str(e)) from e
