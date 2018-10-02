try:
    import psycopg2
except ImportError:
    raise ImportError('In order to use quma with PostgreSQL you '
                      'need to install psycopg2 or psycopg2cffi')


from psycopg2.extras import (
    DictCursor,
    DictRow,
)

from .. import (
    conn,
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
        self.__class__.__dict__['_index'].__set__(self, cursor.index)
        self[:] = [None] * len(cursor.description)

    def __getattribute__(self, attr):
        # Lookup fields in the query result
        try:
            cls = super().__getattribute__('__class__')
            index = cls.__dict__['_index']
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
            if attr.startswith('_'):
                attr = attr[1:]
            else:
                raise AttributeError
            return super().__getattribute__(attr)
        except AttributeError:
            msg = 'Row has no field with the name "{}"'.format(attr)
            raise AttributeError(msg)

    def __setattr__(self, attr, value):
        index = self.__class__.__dict__['_index']
        list.__setitem__(self, index.__get__(self)[attr], value)


class PostgresChangelingCursor(DictCursor):
    def __init__(self, *args, **kwargs):
        kwargs['row_factory'] = PostgresChangelingRow
        super(DictCursor, self).__init__(*args, **kwargs)
        self._prefetch = 1


class Connection(conn.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)

        self.hostname = self.url.hostname or 'localhost'
        self.port = self.url.port or 5432
        if self.changeling:
            self.factory = PostgresChangelingCursor
        else:
            self.factory = psycopg2.extras.DictCursor

        self._init_conn(**kwargs)

    def get_cursor_attr(self, cursor, key):
        # PG is the only one of the supported DBMS which
        # raises an error when fetchall is called after
        # a CREATE, INSERT, UPDATE and so on.
        # mysqlclient and sqlite3 return an empty tuple.
        # We do it that way too to provide an uniform api.
        if key in ('fetchall', 'fetchmany'):
            def fetch(*args, **kwargs):
                try:
                    return getattr(cursor, key)(*args, **kwargs)
                except psycopg2.ProgrammingError as e:
                    if str(e) == 'no results to fetch':
                        return ()
                    raise exc.FetchError(e)
            return fetch
        return getattr(cursor, key)

    def create_conn(self):
        return psycopg2.connect(
            database=self.database,
            user=self.username,
            password=self.password,
            host=self.hostname,
            port=self.port,
            cursor_factory=self.factory)

    def enable_autocommit_if(self, autocommit, conn):
        if autocommit:
            conn.autocommit = True
        return conn

    def disable_autocommit(self, conn):
        conn.autocommit = False
        return conn

    def _check(self, conn):
        try:
            cur = conn.cursor()
            cur.execute('SELECT 1')
        except psycopg2.OperationalError:
            raise exc.OperationalError
