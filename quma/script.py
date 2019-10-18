import sys

from .query import Query

try:
    from mako.lookup import TemplateLookup
    from mako.template import Template
except ImportError:
    Template = None


class Script(object):
    def __init__(
        self, content, echo, is_template, sqldirs, prepare_params=None
    ):
        self.echo = echo
        self.content = content
        self.prepare_params = prepare_params
        self.is_template = is_template
        self.sqldirs = sqldirs
        self.params = None

    def __call__(self, cursor, *args, prepare_params=None, **kwargs):
        return Query(self, cursor, args, kwargs, prepare_params)

    def __str__(self):
        return self.content

    def mogrify(self, cursor, content, params):
        if content:
            sys.stdout.write('-' * 50)
            sys.stdout.write('\n')
            try:
                sys.stdout.write(cursor.mogrify(content, params))
            except AttributeError:
                sys.stdout.write(content)

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
                lookup = TemplateLookup(directories=self.sqldirs)
                return (
                    Template(self.content, lookup=lookup).render(**params),
                    params,
                )
            except TypeError:
                raise ImportError('To use templates you need to install Mako')
        return self.content, params

    def execute(self, cursor, args, kwargs, prepare_params=None):
        if args:
            content, params = self._prepare(cursor, args, prepare_params)
        else:
            content, params = self._prepare(cursor, kwargs, prepare_params)
        try:
            cursor.execute(content, params)
        finally:
            self.echo and self.mogrify(cursor, content, params)


class CursorScript(object):
    def __init__(self, script, cursor):
        self.script = script
        self.cursor = cursor

    def __call__(self, *args, **kwargs):
        return self.script(self.cursor, *args, **kwargs)

    def __str__(self):
        return self.script.content
