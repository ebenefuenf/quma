from importlib.machinery import SourceFileLoader
from itertools import chain
from pathlib import Path

import psycopg2

from . import exc

try:
    from mako.template import Template
except ImportError:
    Template = None


class Cursor(object):
    def __init__(self, pool, carrier=None, factory=None):
        self.pool = pool
        self.carrier = carrier
        self.conn = None
        self.cursor = None

    def __enter__(self):
        return self.create_cursor()

    def __exit__(self, *args):
        self.close()

    def __call__(self):
        return self.create_cursor()

    def create_cursor(self):
        if self.carrier:
            if hasattr(self.carrier, 'conn'):
                self.conn = self.carrier.conn
            else:
                self.conn = self.carrier.conn = self.pool.getconn()
        else:
            self.conn = self.pool.getconn()
        self.cursor = self.conn.cursor(cursor_factory=self.pool.factory)
        return self

    def close(self):
        self.cursor.close()

        # If the connection is bound to the carrier it
        # needs to be returned manually.
        if not hasattr(self.carrier, 'conn'):
            self.pool.putconn(self.conn)

    def commit(self):
        self.conn.commit()

    def rollback(self):
        self.conn.rollback()

    def __getattr__(self, attr):
        return getattr(self.cursor, attr)


class Query(object):
    def __init__(self, query, show, is_template, context_callback=None):
        self.show = show
        self.query = query
        self.context_callback = context_callback
        self.is_template = is_template
        self.context = None

    def __call__(self, cursor, **kwargs):
        self.excecute(cursor, kwargs)
        try:
            return cursor.fetchall()
        except psycopg2.ProgrammingError as e:
            print(cursor.description)
            if str(e) == 'no results to fetch':
                return None
            raise e

    def __str__(self):
        return self.query

    def print_sql(self, cursor):
        if cursor.query:
            print('-' * 50)
            print(cursor.query.decode('utf-8'))

    def prepare(self, cursor, kwargs):
        context = {}

        if self.context_callback:
            context = self.context_callback(cursor.carrier, context)

        context.update(kwargs)

        if self.is_template:
            try:
                return Template(self.query).render(**context), context
            except TypeError:
                raise Exception(
                    'To use templates (*.msql) you need to install Mako')
        return self.query, context

    def excecute(self, cursor, kwargs):
        query, context = self.prepare(cursor, kwargs)
        try:
            cursor.execute(query, context)
        finally:
            self.show and self.print_sql(cursor)

    def get(self, cursor, **kwargs):
        try:
            self.excecute(cursor, kwargs)
        finally:
            self.show and self.print_sql(cursor)
        rowcount = cursor.rowcount
        if rowcount == 0:
            raise exc.DoesNotExistError()
        if rowcount > 1:
            raise exc.MultipleRecordsError()
        return cursor.fetchone()


class Namespace(object):
    def __init__(self, db, sqldir):
        self.db = db
        self.sqldir = sqldir
        self.cache = db.cache
        self.show = db.show
        self.context_callback = None
        self._queries = {}
        self.collect_queries()

    def collect_queries(self):
        sqlfiles = chain(self.sqldir.glob('*.sql'),
                         self.sqldir.glob('*.msql'))

        for sqlfile in sqlfiles:
            filename = Path(sqlfile.name)
            attr = filename.stem
            ext = filename.suffix

            if hasattr(self, attr):
                # We have real namespace method which shadows
                # this file
                attr = f'_{attr}'

            with open(sqlfile, 'r') as f:
                self._queries[attr] = Query(
                    f.read(),
                    self.show,
                    ext.lower() == '.msql',
                    context_callback=self.context_callback)

    def __getattr__(self, attr):
        if self.cache:
            if attr not in self._queries:
                raise AttributeError()
            return self._queries[attr]

        if attr.startswith('_'):
            # unshadow - see collect_queries
            attr = attr[1:]

        sqlfile = self.sqldir / f'{attr}.sql'
        if not sqlfile.is_file():
            sqlfile = self.sqldir / f'{attr}.msql'
        with open(sqlfile, 'r') as f:
            return Query(f.read(),
                         self.show,
                         Path(sqlfile).suffix == '.msql',
                         context_callback=self.context_callback)


class Database(type):
    def __getattr__(cls, attr):
        if attr not in cls.namespaces:
            raise AttributeError()
        return cls.namespaces[attr]


class db(object, metaclass=Database):
    namespaces = {}
    context_callback = None

    def __init__(self, carrier=None):
        self.carrier = carrier

    @classmethod
    def register_namespace(cls, sqldir):
        for path in Path(sqldir).iterdir():
            if path.is_dir():
                ns = path.name
                try:
                    mod_path = str(path / '__init__.py')
                    mod_name = f'quma.mapping.{ns}'
                    module = SourceFileLoader(mod_name, mod_path).load_module()
                    # snake_case to CamelCase
                    class_name = ''.join([s.title() for s in ns.split('_')])
                    ns_class = getattr(module, class_name)
                    if hasattr(ns_class, 'alias'):
                        cls.namespaces[ns_class.alias] = ns_class(cls, path)
                    cls.namespaces[ns] = ns_class(cls, path)
                except (AttributeError, FileNotFoundError):
                    cls.namespaces[ns] = Namespace(cls, path)

    @classmethod
    def init(cls, pool, sqldirs, cache=True, show=False,
             context_callback=None):
        cls.namespaces = {}
        cls.pool = pool
        cls.cache = cache
        cls.show = show
        cls.context_callback = context_callback
        for sqldir in sqldirs:
            cls.register_namespace(sqldir)

    @property
    def cursor(self):
        return Cursor(self.pool, self.carrier)
