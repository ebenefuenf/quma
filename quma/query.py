import sys

from .result import Result

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
