try:
    import psycopg2
except ImportError as e:
    raise ImportError(
        "In order to use quma with PostgreSQL you need to install psycopg2"
    ) from e


from typing import Any

from psycopg2.extensions import TRANSACTION_STATUS_IDLE
from psycopg2.extras import (
    DictCursor,
    DictRow,
)

from .. import (
    conn,
    errors,
    exc,
)


class PostgresChangelingRow(DictRow):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0]), key (row['field']) or by attr (row.field).
    """

    __slots__ = DictRow.__slots__

    def __init__(self, cursor):
        """
        Overwrites DictRow.__init__().

        There self._index is set directly. As we overwrite __setattr__
        we need to do it using the __dict__ of the class. Otherwise
        there would be a recursion error
        """
        self.__class__.__dict__["_index"].__set__(self, cursor.index)
        self[:] = [None] * len(cursor.description)

    def __getattribute__(self, attr):
        # Lookup fields in the query result
        try:
            cls = super().__getattribute__("__class__")
            index = cls.__dict__["_index"]
            return list.__getitem__(self, index.__get__(self)[attr])
        except (AttributeError, KeyError):
            pass
        # Try to return members of DictRow itself. For example .count()
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            pass
        # Try to return "hidden" DictRow members.
        #
        # Example: if there is a field 'count' in the result
        # row you can't access the original method 'count' of
        # the DictRow object. If the original name is prefixed
        # with _ the underscore is removed tried again.
        # e. g. row._count(value) will be row.count(value)
        try:
            if attr.startswith("_"):
                attr = attr[1:]
            else:
                raise AttributeError
            return super().__getattribute__(attr)
        except AttributeError as e:
            msg = f'Row has no field with the name "{attr}"'
            raise AttributeError(msg) from e

    def __setattr__(self, attr, value):
        index = self.__class__.__dict__["_index"]
        list.__setitem__(self, index.__get__(self)[attr], value)


class PostgresChangelingCursor(DictCursor):
    def __init__(self, *args, **kwargs):
        kwargs["row_factory"] = PostgresChangelingRow
        super(DictCursor, self).__init__(*args, **kwargs)
        self._prefetch = 1


class StartedNonConforming:
    """For a connection that started with standard_conforming_strings off.
    psycopg2 chooses its E'' prefix once, while connecting, but libpq stops
    doubling backslashes when the setting goes on, so ``\\'`` in a value would end
    its string. Costs a check per statement, on these connections only."""

    def _check_values(self: Any, values):
        status = self.connection.info.parameter_status
        if values and status("standard_conforming_strings") == "on":
            raise exc.APIError(
                "This connection started with standard_conforming_strings = "
                "off, and it's on now, so psycopg2 can't escape values: one "
                "could run as SQL. Set it while connecting, with options='-c "
                "standard_conforming_strings=on'."
            )

    def execute(self: Any, query, vars=None):
        self._check_values(vars)
        return super().execute(query, vars)

    def executemany(self: Any, query, vars_list):
        self._check_values(vars_list)
        return super().executemany(query, vars_list)

    def callproc(self: Any, procname, vars=None):
        self._check_values(vars)
        return super().callproc(procname, vars)

    def mogrify(self: Any, query, vars=None):
        self._check_values(vars)
        return super().mogrify(query, vars)


class NonConformingCursor(StartedNonConforming, DictCursor):
    pass


class NonConformingChangelingCursor(
    StartedNonConforming, PostgresChangelingCursor
):
    pass


class Connection(conn.PostgresTransactions, conn.Connection):
    dialect = "postgresql"
    driver_error = psycopg2.Error

    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)

        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 5432
        if self.changeling:
            self.factory = PostgresChangelingCursor
            self.nonconforming_factory = NonConformingChangelingCursor
        else:
            self.factory = DictCursor
            self.nonconforming_factory = NonConformingCursor
        self._init_conn()

    def get_cursor_attr(self, cursor, key):
        # PG is the only one of the supported DBMS which
        # raises an error when fetchall is called after
        # a CREATE, INSERT, UPDATE and so on.
        # mysqlclient and sqlite3 return an empty tuple.
        # We do it that way too to provide an uniform api.
        if key in ("fetchall", "fetchmany"):

            def fetch(*args, **kwargs):
                try:
                    return getattr(cursor, key)(*args, **kwargs)
                except psycopg2.ProgrammingError as e:
                    if str(e) == "no results to fetch":
                        return ()
                    raise

            return fetch
        return getattr(cursor, key)

    def create_conn(self, **kwargs):
        try:
            conn = psycopg2.connect(
                database=self.database,
                user=self.username,
                password=self.password,
                host=self.hostname,
                port=self.port,
                cursor_factory=self.factory,
                **kwargs,
            )
        except psycopg2.Error as e:
            raise errors.connection_error(e, self.dialect) from e
        status = conn.info.parameter_status("standard_conforming_strings")
        if status == "off":
            conn.cursor_factory = self.nonconforming_factory
        return conn

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.autocommit = True
        return conn

    def disable_autocommit(self, conn):
        conn.autocommit = False
        return conn

    def rollback(self, conn):
        # psycopg2's rollback() does nothing in autocommit, also if a BEGIN
        # statement opened a transaction.
        if not conn.autocommit:
            conn.rollback()
        elif conn.get_transaction_status() != TRANSACTION_STATUS_IDLE:
            with conn.cursor() as cursor:
                cursor.execute("ROLLBACK")

    def mogrify(self, cursor, content, params):
        return cursor.mogrify(content, params).decode("utf-8")

    def _check(self, conn):
        # psycopg2 raises InterfaceError, not OperationalError, if closed.
        if conn.closed:
            raise exc.ConnectionLost("The connection is closed.")
        idle = conn.get_transaction_status() == TRANSACTION_STATUS_IDLE
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except psycopg2.OperationalError as e:
            raise exc.ConnectionLost(str(e)) from e
        if idle:
            # End the check's transaction, it would block enabling autocommit.
            conn.rollback()
