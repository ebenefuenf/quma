from . import exc


class ManyResult(object):
    def __init__(self, cursor, size):
        self.cursor = cursor
        self.size = self.cursor.arraysize if size is None else size
        self.result = self.cursor.fetchmany(self.size)

    def __iter__(self):
        for row in self.result:
            yield row

    def __len__(self):
        return len(self.result)

    def next(self, size=None):
        return ManyResult(self.cursor, size)


class Query(object):
    """
    The query object is the value you get when you run a query,
    i. e. call a :class:`Script` object.

    """

    def __init__(self, script, cursor, args, kwargs, prepare_params):
        self.script = script
        self.cursor = cursor
        self.args = args
        self.kwargs = kwargs
        self.prepare_params = prepare_params

    def __iter__(self):
        self.run()
        return (row for row in self._fetch(self.cursor.fetchall))

    def __len__(self):
        self.run()
        if self.cursor.has_rowcount:
            return self.cursor.rowcount
        else:
            result = self._fetch(self.cursor.fetchall)
            return len(result)

    def run(self):
        """Execute the query and ignore the result"""
        self.script.execute(self.cursor,
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
        self.run()
        return self._fetch(self.cursor.fetchall)

    def count(self):
        """Return the length of the result."""
        return len(self.all())

    def one(self):
        """Get exactly one row and check if only one exists.
        Otherwise raise an error.
        """
        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRowsError()

        self.run()

        # SQLite does not support rowcount
        if self.cursor.has_rowcount:
            check_rowcount(self.cursor.rowcount)
            return self._fetch(self.cursor.fetchone)
        else:
            result = self._fetch(self.cursor.fetchall)
            check_rowcount(len(result))
            return result[0]

    def value(self):
        """Call :func:`one` and return the first column."""
        return self.first()[0]

    def first(self):
        """Get exactly one row and return None if there is no
        row present in the result."""
        self.run()
        try:
            return self._fetch(self.cursor.fetchall)[0]
        except IndexError:
            return None

    def exists(self):
        """Return if the query's result has rows"""
        self.run()
        return len(self._fetch(self.cursor.fetchall)) > 0

    def many(self, size=None):
        """Call the :func:`fetchmany` method of the raw cursor.

        :param size: The number of columns to be returned. If not
            given use the default value of the driver.
        """
        self.run()
        return ManyResult(self.cursor, size)
