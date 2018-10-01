import sys
from functools import partial

from . import exc

try:
    from mako.template import Template
except ImportError:
    Template = None


class Query(object):
    def __init__(self, query, show, is_template, prepare_params=None):
        self.show = show
        self.query = query
        self.prepare_params = prepare_params
        self.is_template = is_template
        self.params = None

    def _fetch(self, func):
        try:
            return func()
        except exc.FetchError as e:
            raise e.error

    def __call__(self, cursor, *args, prepare_params=None, **kwargs):
        self._execute(cursor, list(args), kwargs, prepare_params)
        return self._fetch(cursor.fetchall)

    def __str__(self):
        return self.query

    def _print_sql(self):
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

    def _execute(self, cursor, args, kwargs, prepare_params=None):
        if args:
            query, params = self._prepare(cursor, args, prepare_params)
        else:
            query, params = self._prepare(cursor, kwargs, prepare_params)
        try:
            cursor.execute(query, params)
        finally:
            self.show and self._print_sql()

    def get(self, cursor, *args, prepare_params=None, **kwargs):
        try:
            self._execute(cursor, list(args), kwargs, prepare_params)
        finally:
            self.show and self._print_sql()

        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRecordsError()

        # SQLite does not support rowcount
        if cursor.has_rowcount:
            check_rowcount(cursor.rowcount)
            return cursor.fetchone()
        else:
            result = cursor.fetchall()
            check_rowcount(len(result))
            return result[0]

    def first(self, cursor, *args, prepare_params=None, **kwargs):
        self._execute(cursor, list(args), kwargs, prepare_params)
        return self._fetch(cursor.fetchall)[0]

    def value(self, cursor, *args, prepare_params=None, **kwargs):
        return self.first(cursor, *args, prepare_params=None, **kwargs)[0]

    def many(self, cursor, size=None, *args, **kwargs):
        if size is None:
            size = cursor.arraysize
        self._execute(cursor, list(args), kwargs)
        return self._fetch(partial(cursor.fetchmany, size))

    def next(self, cursor, size=None):
        if size is None:
            size = cursor.arraysize
        return self._fetch(partial(cursor.fetchmany, size))

    def count(self, cursor, *args, prepare_params=None, **kwargs):
        self._execute(cursor, list(args), kwargs, prepare_params)

        if cursor.has_rowcount:
            return cursor.rowcount
        else:
            result = cursor.fetchall()
            return len(result)


class CursorQuery(object):
    def __init__(self, query, cursor):
        self.query = query
        self.cursor = cursor

    def __call__(self, *args, **kwargs):
        return self.query(self.cursor, *args, **kwargs)

    def __str__(self):
        return self.query.query

    def get(self, *args, prepare_params=None, **kwargs):
        return self.query.get(self.cursor, *args,
                              prepare_params=prepare_params, **kwargs)

    def first(self, *args, **kwargs):
        return self.query.first(self.cursor, *args, **kwargs)

    def value(self, *args, **kwargs):
        return self.query.first(self.cursor, *args, **kwargs)[0]

    def many(self, *args, **kwargs):
        return self.query.many(self.cursor, *args, **kwargs)

    def next(self, size=None):
        return self.query.next(self.cursor, size=size)

    def count(self, *args, **kwargs):
        return self.query.count(self.cursor, *args, **kwargs)
