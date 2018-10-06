import sys
from functools import partial

from . import exc

try:
    from mako.template import Template
except ImportError:
    Template = None


class Result(object):
    def __init__(self, query, cursor, args, kwargs, prepare_params):
        self.query = query
        self.cursor = cursor
        self.args = args
        self.kwargs = kwargs
        self.prepare_params = prepare_params
        self._execute()

    def __iter__(self):
        for row in self._fetch(self.cursor.fetchall):
            yield row

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

    def get(self):
        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRecordsError()

        # SQLite does not support rowcount
        if self.cursor.has_rowcount:
            check_rowcount(self.cursor.rowcount)
            return self._fetch(self.cursor.fetchone)
        else:
            result = self._fetch(self.cursor.fetchall)
            check_rowcount(len(result))
            return result[0]

    @property
    def one(self):
        return self.get()

    @property
    def first(self):
        return self._fetch(self.cursor.fetchall)[0]

    @property
    def value(self):
        return self.first[0]

    def many(self, size=None):
        if size is None:
            size = self.cursor.arraysize
        return self._fetch(partial(self.cursor.fetchmany, size))


class Query(object):
    def __init__(self, query, show, is_template, prepare_params=None):
        self.show = show
        self.query = query
        self.prepare_params = prepare_params
        self.is_template = is_template
        self.params = None

    def __call__(self, cursor, *args, prepare_params=None, **kwargs):
        return Result(self, cursor, args, kwargs, prepare_params)

    def __str__(self):
        return self.query

    def print_sql(self):
        if self.query:
            sys.stdout.write('-' * 50)
            sys.stdout.write('\n')
            sys.stdout.write(self.query)

    def _prepare(self, cursor, payload, prepare_params):
        # create an empty list if payload == args
        # create an empty dict if payload == kwargs
        params = type(payload)()

        init = prepare_params or self.prepare_params
        if init:
            params = init(cursor.carrier, params)

        try:
            params.update(payload)
        except AttributeError:
            params.extend(payload)

        if self.is_template:
            try:
                return Template(self.query).render(**params), params
            except TypeError:
                raise ImportError(
                    'To use templates you need to install Mako')
        return self.query, params

    def execute(self, cursor, args, kwargs, prepare_params=None):
        if args:
            query, params = self._prepare(cursor, args, prepare_params)
        else:
            query, params = self._prepare(cursor, kwargs, prepare_params)
        try:
            cursor.execute(query, params)
        finally:
            self.show and self.print_sql()


class CursorQuery(object):
    def __init__(self, query, cursor):
        self.query = query
        self.cursor = cursor

    def __call__(self, *args, **kwargs):
        return self.query(self.cursor, *args, **kwargs)

    def __str__(self):
        return self.query.query
