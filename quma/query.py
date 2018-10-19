from . import exc


class ManyResult(object):
    def __init__(self, query):
        self.query = query
        self.cursor = query.cursor
        self._has_been_executed = False

    def _run(self):
        self.query.run()
        self._has_been_executed = True

    def get(self, size=None):
        """Call the :func:`fetchmany` method of the raw cursor.

        :param size: The number of rows to be returned. If not
            given use the default value of the driver.
        """
        size = self.cursor.arraysize if size is None else size
        if not self._has_been_executed:
            self._run()
        return self.cursor.fetchmany(size)


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
        self._has_been_executed = False
        self._result_cache = None

    def run(self):
        """Execute the query using the DBAPI driver."""
        self.script.execute(self.cursor,
                            list(self.args),
                            self.kwargs,
                            self.prepare_params)
        self._has_been_executed = True
        self._result_cache = None
        return self

    def _fetch(self):
        if not self._has_been_executed:
            self.run()
        if self._result_cache is None:
            try:
                self._result_cache = self.cursor.fetchall()
            except exc.FetchError as e:
                raise e.error
        return self._result_cache

    def __getattr__(self, key):
        return getattr(self.cursor, key)

    def __getitem__(self, index):
        return self._fetch()[index]

    def __iter__(self):
        for row in self._fetch():
            yield row

    def __bool__(self):
        return len(self._fetch()) > 0

    def _len(self):
        self.run()
        if self.cursor.has_rowcount:
            return self.cursor.rowcount
        else:
            return len(self._fetch())

    def __len__(self):
        return self._len()

    def count(self):
        """Return the length of the result."""
        return self._len()

    def all(self):
        """Return a list of all results"""
        return self._fetch()

    def one(self):
        """Get exactly one row and check if only one exists,
        otherwise raise an error.
        """
        if not self._has_been_executed:
            self.run()

        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRowsError()

        # SQLite does not support rowcount
        if self.cursor.has_rowcount:
            check_rowcount(self.cursor.rowcount)
            result = self._fetch()
        else:
            result = self._fetch()
            check_rowcount(len(result))
        return result[0]

    def value(self, key=0):
        """Call :func:`one` and return the first column by default.

        :param key: Return the value at ``key``'s position instead
            of the first column."""
        return self.one()[key]

    def first(self):
        """Get exactly one row and return None if there is no
        row present in the result."""
        try:
            return self._fetch()[0]
        except IndexError:
            return None

    def exists(self):
        """Return if the query's result has rows."""
        return len(self._fetch()) > 0

    def many(self):
        """Return a ManyResult object initialized with
        this query object.
        """
        return ManyResult(self)

    def unbunch(self, size=None):
        """Return a generator that simplifies the use of fetchmany.

        :param size: The number of rows to be fetched per
            fetchmany call. If not given use the default value
            of the driver.
        """
        size = self.cursor.arraysize if size is None else size
        self.run()
        while True:
            results = self.cursor.fetchmany(size)
            if not results:
                break
            for result in results:
                yield result
