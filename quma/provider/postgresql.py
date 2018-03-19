try:
    import psycopg2
except ImportError:
    try:
        from psycopg2cffi import compat
    except ImportError:
            raise ImportError('In order to use quma with PostgreSQL you'
                              'need to install psycopg2 or psycopg2cffi')
    else:
        compat.register()
from psycopg2.extras import (
    DictCursor,
    DictRow,
)
from psycopg2.pool import ThreadedConnectionPool

from .. import core


class PostgresChangelingRow(DictRow):
    """
    A row object that allows by-column-name access to data.

    Either by index (row[0], row['field']) or by attr (row.field).
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

    def __getattr__(self, attr):
        try:
            return list.__getitem__(self, self._index[attr])
        except KeyError:
            raise AttributeError(f'Row has no field with the name "{attr}"')

    def __setattr__(self, attr, value):
        index = self.__class__.__dict__['_index']
        list.__setitem__(self, index.__get__(self)[attr], value)


class PostgresChangelingCursor(DictCursor):
    def __init__(self, *args, **kwargs):
        kwargs['row_factory'] = PostgresChangelingRow
        super(DictCursor, self).__init__(*args, **kwargs)
        self._prefetch = 1


class Connection(core.Connection):
    def __init__(self, url, **kwargs):
        super().__init__(url, **kwargs)

        self.hostname = self.url.hostname or 'localhost'
        self.port = self.url.port or 5432
        if self.changeling:
            self.factory = PostgresChangelingCursor
        else:
            self.factory = psycopg2.extras.DictCursor

        self._init_conn(**kwargs)

    def create_conn(self):
        return psycopg2.connect(
            database=self.database,
            user=self.username,
            password=self.password,
            host=self.hostname,
            port=self.port,
            cursor_factory=self.factory)


class Pool(Connection):
    def __init__(self, url, **kwargs):
        self.minconn = int(kwargs.pop('minconn', 1))
        self.maxconn = int(kwargs.pop('maxconn', 10))

        super().__init__(url, **kwargs)

    def _init_conn(self, **kwargs):
        self.pool = ThreadedConnectionPool
        self.conn = self.pool(self.minconn,
                              self.maxconn,
                              database=self.database,
                              user=self.username,
                              password=self.password,
                              host=self.hostname,
                              port=self.port,
                              cursor_factory=self.factory)

    def get(self):
        return self.conn.getconn()

    def put(self, conn):
        return self.conn.putconn(conn)

    def close(self):
        self.conn.closeall()
        self.conn = None
