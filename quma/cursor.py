try:
    from psycopg2.extras import (
        DictCursor,
        DictRow,
    )
except ImportError:
    DictCursor = None
    DictRow = None


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
