from importlib import import_module
from importlib.machinery import SourceFileLoader
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse
from typing import TypeVar

import psycopg2

from . import exc
from . import core
from . import pool

try:
    from mako.template import Template
except ImportError:
    Template = None


class CursorWrapper(object):
    def __init__(self, conn, raw_cursor):
        self.raw_cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key):
        try:
            return getattr(self.raw_cursor, key)
        except AttributeError as e:
            raise e


CursorType = TypeVar('CursorType', bound='Cursor')


class Cursor(object):
    def __init__(self, conn: core.Connection, carrier=None) -> None:
        self.conn = conn
        self.carrier = carrier
        self.raw_conn = None
        self.raw_cursor: CursorWrapper

    def __enter__(self):
        return self.create_cursor()

    def __exit__(self, *args):
        if self.conn:
            self.put()

    def __call__(self: CursorType) -> CursorType:
        return self.create_cursor()

    def create_cursor(self: CursorType) -> CursorType:
        if self.carrier:
            if hasattr(self.carrier, '_quma_conn'):
                self.raw_conn = self.carrier._quma_conn
            else:
                self.raw_conn = self.carrier._quma_conn = self.conn.get()
        else:
            self.raw_conn = self.conn.get()
        self.raw_cursor = CursorWrapper(self.conn,
                                        self.conn.cursor(self.raw_conn))
        return self

    def put(self):
        self.raw_cursor.close()

        # If the connection is bound to the carrier it
        # needs to be returned manually.
        if not hasattr(self.carrier, '_quma_conn'):
            self.conn.put(self.raw_conn)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def get_conn_attr(self, attr):
        return getattr(self.raw_conn, attr)

    def set_conn_attr(self, attr, value):
        setattr(self.raw_conn, attr, value)

    def __getattr__(self, attr):
        return getattr(self.raw_cursor, attr)


class Query(object):
    def __init__(self, query, show, is_template, init_params=None):
        self.show = show
        self.query = query
        self.init_params = init_params
        self.is_template = is_template
        self.params = None

    def __call__(self, cursor, *args, **kwargs):
        self._execute(cursor, list(args), kwargs)
        try:
            return cursor.fetchall()
        except psycopg2.ProgrammingError as e:
            if str(e) == 'no results to fetch':
                return None
            raise e

    def __str__(self):
        return self.query

    def _print_sql(self, cursor):
        if cursor.query:
            print('-' * 50)
            print(cursor.query.decode('utf-8'))

    def _prepare(self, cursor, payload, init_params):
        params = type(payload)()

        init = init_params or self.init_params
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
                raise Exception(
                    'To use templates (*.msql) you need to install Mako')
        return self.query, params

    def _execute(self, cursor, args, kwargs, init_params=None):
        if args:
            query, params = self._prepare(cursor, args, init_params)
        else:
            query, params = self._prepare(cursor, kwargs, init_params)
        try:
            cursor.execute(query, params)
        finally:
            self.show and self._print_sql(cursor)

    def get(self, cursor, *args, init_params=None, **kwargs):
        try:
            self._execute(cursor, list(args), kwargs, init_params)
        finally:
            self.show and self._print_sql(cursor)

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
        self._queries = {}
        self._collect_queries()

    def _collect_queries(self):
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
                    init_params=self.db.init_params)

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
                init_params=self.db.init_params)


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
        self.init_params = kwargs.pop('init_params', None)
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
    module = import_module(f'quma.provider.{module_name}')
    conn = getattr(module, 'Connection')(url, **kwargs)
    try:
        if scheme[1].lower() == 'pool':
            return pool.Pool(conn, **kwargs)
        else:
            raise ValueError('Wrong scheme. Only "provider://" or '
                             '"provider+pool://" are allowed')
    except IndexError:
        return conn
