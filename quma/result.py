from functools import partial

from . import exc


class Result(object):
    """
    The result object is the value you get when you run a query,
    i. e. call a :class:`Query` object.

    """

    def __init__(self, query, cursor, args, kwargs, prepare_params):
        self.query = query
        self.cursor = cursor
        self.args = args
        self.kwargs = kwargs
        self.prepare_params = prepare_params
        self._execute()

    def __iter__(self):
        return (row for row in self._fetch(self.cursor.fetchall))

    def __len__(self):
        if self.cursor.has_rowcount:
            return self.cursor.rowcount
        else:
            result = self._fetch(self.cursor.fetchall)
            return len(result)

    def _execute(self):
        self.query.execute(self.cursor,
                           list(self.args),
                           self.kwargs,
                           self.prepare_params)

    def _fetch(self, func):
        try:
            return func()
        except exc.FetchError as e:
            raise e.error

    def all(self):
        """Return a list of all results"""
        return self._fetch(self.cursor.fetchall)

    def count(self):
        """Return the length of the result."""
        return len(self.all())

    def one(self):
        """Get exactly one row and check if only one exists."""
        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRowsError()

        # SQLite does not support rowcount
        if self.cursor.has_rowcount:
            check_rowcount(self.cursor.rowcount)
            return self._fetch(self.cursor.fetchone)
        else:
            result = self._fetch(self.cursor.fetchall)
            check_rowcount(len(result))
            return result[0]

    def first(self):
        """Get exactly one row and return None if there is no
        row present in the result."""
        try:
            return self._fetch(self.cursor.fetchall)[0]
        except IndexError:
            return None

    def value(self):
        """Call :func:`one` and return the first column."""
        return self.first()[0]

    def many(self, size=None):
        """Call the :func:`fetchmany` method of the raw cursor.

        :param size: The number of columns to be returned. If not
            given use the default value of the driver.
        """
        if size is None:
            size = self.cursor.arraysize
        return self._fetch(partial(self.cursor.fetchmany, size))
