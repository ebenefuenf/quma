try:
    import psycopg
except ImportError as e:
    raise ImportError(
        "In order to use quma with PostgreSQL you need to install psycopg"
    ) from e

from functools import partial

from psycopg.pq import TransactionStatus

from .. import (
    conn,
    exc,
)


class Row(list):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0]) or key (row['field']).
    """

    __slots__ = ("_index",)

    def __init__(self, values, index):
        super().__init__(values)
        object.__setattr__(self, "_index", index)

    def __getitem__(self, x):
        if not isinstance(x, (int, slice)):
            x = self._index[x]
        return super().__getitem__(x)

    def __setitem__(self, x, value):
        if not isinstance(x, (int, slice)):
            x = self._index[x]
        super().__setitem__(x, value)

    def __contains__(self, key):
        return key in self._index

    def __reduce__(self):
        return (self.__class__, (list(self), self._index))

    def keys(self):
        return iter(self._index)

    def values(self):
        return (list.__getitem__(self, i) for i in self._index.values())

    def items(self):
        return (
            (key, list.__getitem__(self, i)) for key, i in self._index.items()
        )

    def get(self, key, default=None):
        try:
            return self[key]
        except (KeyError, IndexError):
            return default

    def copy(self):
        return dict(self.items())


class ChangelingRow(Row):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0]), key (row['field']) or by attr (row.field).
    """

    __slots__ = ()

    def __getattribute__(self, attr):
        # Lookup fields in the query result
        index = object.__getattribute__(self, "_index")
        try:
            return list.__getitem__(self, index[attr])
        except KeyError:
            pass
        # Try to return members of Row itself. For example .count()
        try:
            return super().__getattribute__(attr)
        except AttributeError:
            pass
        # Try to return "hidden" Row members.
        #
        # Example: if there is a field 'count' in the result
        # row you can't access the original method 'count' of
        # the Row object. If the original name is prefixed
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
        index = object.__getattribute__(self, "_index")
        list.__setitem__(self, index[attr], value)


def row_factory(row_class):
    def factory(cursor):
        description = cursor.description or ()
        index = {column.name: i for i, column in enumerate(description)}
        return partial(row_class, index=index)

    return factory


class Cursor(psycopg.ClientCursor):
    def execute(self, query, params=None, **kwargs):
        super().execute(query, params, **kwargs)
        # Like psycopg2, expose the result of the last statement
        # if the query consists of multiple statements.
        while self.nextset():
            pass
        return self


class Connection(conn.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, kwargs)

        self.hostname = self.url.hostname or "localhost"
        self.port = self.url.port or 5432
        if self.changeling:
            self.factory = row_factory(ChangelingRow)
        else:
            self.factory = row_factory(Row)
        self._init_conn()

    def get_cursor_attr(self, cursor, key):
        # PostgreSQL drivers raise an error when fetchall is called
        # after a CREATE, INSERT, UPDATE and so on. mysqlclient and
        # sqlite3 return an empty tuple. We do it that way too to
        # provide an uniform api.
        if key in ("fetchall", "fetchmany"):

            def fetch(*args, **kwargs):
                try:
                    return getattr(cursor, key)(*args, **kwargs)
                except psycopg.ProgrammingError as e:
                    if cursor.description is None:
                        return ()
                    raise exc.FetchError(e) from e

            return fetch
        return getattr(cursor, key)

    def create_conn(self, **kwargs):
        try:
            return psycopg.connect(
                dbname=self.database,
                user=self.username,
                password=self.password,
                host=self.hostname,
                port=self.port,
                cursor_factory=Cursor,
                row_factory=self.factory,
                **kwargs,
            )
        except psycopg.OperationalError as e:
            raise exc.ConnectionError(str(e)) from e

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.autocommit = True
        return conn

    def disable_autocommit(self, conn):
        conn.autocommit = False
        return conn

    def mogrify(self, cursor, content, params):
        # ClientCursor.mogrify() discards the cursor's current result.
        with psycopg.ClientCursor(cursor.connection) as mogrifier:
            return mogrifier.mogrify(content, params)

    def _check(self, conn):
        idle = conn.info.transaction_status == TransactionStatus.IDLE
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        except psycopg.OperationalError as e:
            raise exc.OperationalError from e
        if idle:
            # End the check's transaction, it would block enabling autocommit.
            conn.rollback()
