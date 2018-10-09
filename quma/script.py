import sys

from .query import Query

try:
    from mako.template import Template
except ImportError:
    Template = None


class Script(object):
    def __init__(self, content, show, is_template, prepare_params=None):
        self.show = show
        self.content = content
        self.prepare_params = prepare_params
        self.is_template = is_template
        self.params = None

    def __call__(self, cursor, *args, prepare_params=None, **kwargs):
        return Query(self, cursor, args, kwargs, prepare_params)

    def __str__(self):
        return self.content

    def print_sql(self):
        if self.content:
            sys.stdout.write('-' * 50)
            sys.stdout.write('\n')
            sys.stdout.write(self.content)

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
                return Template(self.content).render(**params), params
            except TypeError:
                raise ImportError(
                    'To use templates you need to install Mako')
        return self.content, params

    def execute(self, cursor, args, kwargs, prepare_params=None):
        if args:
            content, params = self._prepare(cursor, args, prepare_params)
        else:
            content, params = self._prepare(cursor, kwargs, prepare_params)
        try:
            cursor.execute(content, params)
        finally:
            self.show and self.print_sql()


class CursorScript(object):
    def __init__(self, script, cursor):
        self.script = script
        self.cursor = cursor

    def __call__(self, *args, **kwargs):
        return self.script(self.cursor, *args, **kwargs)

    def __str__(self):
        return self.script.content
