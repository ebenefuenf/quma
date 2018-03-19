from importlib import import_module
from importlib.machinery import SourceFileLoader
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse

import psycopg2

from . import exc

try:
    from mako.template import Template
except ImportError:
    Template = None


class CursorWrapper(object):
    def __init__(self, conn, dbapi_cursor):
        self.dbapi_cursor = dbapi_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key):
        try:
            return getattr(self.dbapi_cursor, key)
        except AttributeError as e:
            raise e


class Cursor(object):
    def __init__(self, conn, carrier=None):
        self.conn = conn
        self.carrier = carrier
        self.dbapi_conn = None
        self.dbapi_cursor = None

    def __enter__(self):
        return self.create_cursor()

    def __exit__(self, *args):
        if self.conn:
            self.put()

    def __call__(self):
        return self.create_cursor()

    def create_cursor(self):
        if self.carrier:
            if hasattr(self.carrier, '_quma_conn'):
                self.dbapi_conn = self.carrier._quma_conn
            else:
                self.dbapi_conn = self.carrier._quma_conn = self.conn.get()
        else:
            self.dbapi_conn = self.conn.get()
        self.dbapi_cursor = CursorWrapper(self.conn,
                                          self.conn.cursor(self.dbapi_conn))
        return self

    def put(self):
        self.dbapi_cursor.close()

        # If the connection is bound to the carrier it
        # needs to be returned manually.
        if not hasattr(self.carrier, '_quma_conn'):
            self.conn.put(self.dbapi_conn)

    def commit(self):
        self.dbapi_conn.commit()

    def rollback(self):
        self.dbapi_conn.rollback()

    def __getattr__(self, attr):
        return getattr(self.dbapi_cursor, attr)


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

        def check_rowcount(rowcount):
            if rowcount == 0:
                raise exc.DoesNotExistError()
            if rowcount > 1:
                raise exc.MultipleRecordsError()

        # SQLite does not support rowcount
        if cursor.has_rowcount:
            rowcount = cursor.rowcount
            check_rowcount(rowcount)
            return cursor.fetchone()
        else:
            result = cursor.fetchall()
            check_rowcount(len(result))
            return result[0]


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
                self._queries[attr] = self.db.query_factory(
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
            return self.db.query_factory(
                f.read(),
                self.show,
                Path(sqlfile).suffix == '.msql',
                context_callback=self.context_callback)


class CallWrapper(object):
    def __init__(self, database, carrier):
        self.database = database
        self.carrier = carrier

    @property
    def cursor(self):
        return Cursor(self.database.conn, self.carrier)


class Database(object):

    def __init__(self, dburi, *args, **kwargs):
        # if the second arg is present it must be sqldirs
        if args and len(args) > 1:
            raise ValueError('Max number of arguments is two')
        elif args and len(args) == 1:
            self.sqldirs = args[0]
        else:
            self.sqldirs = kwargs.pop('sqldirs', [])

        self.query_factory = kwargs.pop('query_factory', Query)
        self.context_callback = kwargs.pop('context_callback', Query)
        self.show = kwargs.pop('show', False)
        self.cache = kwargs.pop('cache', False)

        # The remaining kwargs are passed to the DBAPI connect call
        self.conn = connect(dburi, **kwargs)

        self.namespaces = {}

        for sqldir in self.sqldirs:
            self.register_namespace(sqldir)

    def __call__(self, carrier=None):
        return CallWrapper(self, carrier)

    def register_namespace(self, sqldir):
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
                        self.namespaces[ns_class.alias] = ns_class(self, path)
                    self.namespaces[ns] = ns_class(self, path)
                except (AttributeError, FileNotFoundError):
                    self.namespaces[ns] = Namespace(self, path)

    def close(self):
        self.conn.close()
        self.conn = None

    def execute(self, sql, **kwargs):
        with self.cursor as c:
            try:
                c.execute(sql, **kwargs)
                c.commit()
            except Exception as e:
                c.rollback()
                raise e

    @property
    def cursor(self):
        return Cursor(self.conn)

    def __getattr__(self, attr):
        if attr not in self.namespaces:
            raise AttributeError()
        return self.namespaces[attr]


def connect(dburi, **kwargs):
    url = urlparse(dburi)
    scheme = url.scheme.split('+')
    module_name = scheme[0]
    class_name = 'Connection'
    try:
        if scheme[1].lower() == 'pool':
            class_name = 'Pool'
    except IndexError:
        pass
    module = import_module(f'quma.provider.{module_name}')
    return getattr(module, class_name)(url, **kwargs)
