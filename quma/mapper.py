from functools import partial
from importlib import import_module
from importlib.machinery import SourceFileLoader
from itertools import chain
from pathlib import Path
import sys
from urllib.parse import urlparse

from . import exc
from . import pool

try:
    from mako.template import Template
except ImportError:
    Template = None


def get_namespace(self, attr):
    if attr in self.namespaces:
        return self.namespaces[attr]

    root = self.namespaces['__root__']
    while root:
        try:
            return getattr(root, attr)
        except AttributeError:
            root = root.shadow
    raise AttributeError


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
            rowcount = cursor.rowcount
            check_rowcount(rowcount)
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


class Namespace(object):
    def __init__(self, db, sqldir, shadow=None):
        self.db = db
        self.sqldir = sqldir
        self.cache = db.cache
        self.show = db.show
        self.shadow = shadow
        self._queries = {}
        if db.cache:
            self._collect_queries(sqldir)

    def _collect_queries(self, sqldir):
        sqlfiles = chain(sqldir.glob(f'*.{self.db.file_ext}'),
                         sqldir.glob(f'*.{self.db.tmpl_ext}'))

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
                    ext.lower() == f'.{self.db.tmpl_ext}',
                    prepare_params=self.db.prepare_params)

    def __getattr__(self, attr):
        if self.cache:
            try:
                return self._queries[attr]
            except KeyError:
                return getattr(self.shadow, attr)

        try:
            sqlfile = self.sqldir / f'{attr}.{self.db.file_ext}'
            if not sqlfile.is_file():
                sqlfile = self.sqldir / f'{attr}.{self.db.tmpl_ext}'
            with open(sqlfile, 'r') as f:
                return self.db.query_factory(
                    f.read(),
                    self.show,
                    Path(sqlfile).suffix == f'.{self.db.tmpl_ext}',
                    prepare_params=self.db.prepare_params)
        except FileNotFoundError:
            return getattr(self.shadow, attr)


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


class CursorNamespace(object):
    def __init__(self, namespace, cursor):
        self.namespace = namespace
        self.cursor = cursor

    def __getattr__(self, attr):
        if type(self.namespace) is Query:
            return getattr(CursorQuery(self.namespace, self.cursor), attr)
        attr_obj = getattr(self.namespace, attr)
        if type(attr_obj) is Query:
            return CursorQuery(attr_obj, self.cursor)
        return attr_obj

    def __call__(self, *args, **kwargs):
        if type(self.namespace) is Query:
            return self.namespace(self.cursor, *args, **kwargs)
        # Should be a custom namespace method
        return self.namespace(*args, **kwargs)


class CarriedConnection(object):
    def __init__(self, conn, raw_conn):
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper(object):
    def __init__(self, conn, raw_cursor):
        self.conn = conn
        self.raw_cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key):
        try:
            return self.conn.get_cursor_attr(self.raw_cursor, key)
        except AttributeError as e:
            raise e


class Cursor(object):
    def __init__(self, conn, namespaces, contextcommit,
                 carrier=None, autocommit=False):
        self.conn = conn
        self.namespaces = namespaces
        self.carrier = carrier
        self.autocommit = autocommit
        self.raw_conn = None
        self.raw_cursor = None
        self.contextcommit = contextcommit

    def __enter__(self):
        return self.create_cursor()

    def __exit__(self, *args):
        if self.contextcommit:
            self.commit()
        else:
            # always call rollback to make sure the transaction ends
            self.rollback()
        if self.conn:
            self.put()

    def __call__(self, autocommit=None):
        return self.create_cursor(autocommit=autocommit)

    def create_cursor(self, autocommit=None):
        autocommit = autocommit if autocommit is not None else self.autocommit
        if self.carrier:
            if hasattr(self.carrier, '__quma_conn__'):
                self.raw_conn = self.carrier.__quma_conn__.raw_conn
            else:
                conn = self.conn.get(autocommit=autocommit)
                self.carrier.__quma_conn__ = CarriedConnection(self.conn, conn)
                self.raw_conn = conn
        else:
            self.raw_conn = self.conn.get(autocommit=autocommit)
        self.raw_cursor = RawCursorWrapper(self.conn,
                                           self.conn.cursor(self.raw_conn))
        if not autocommit:
            self.raw_cursor = self.conn.init_transaction(self.raw_cursor)
        return self

    def put(self, force=False):
        """
        Ensures that not only the cursor is closed but also
        the connection if necessary.
        """
        self.raw_cursor.close()

        # If the connection is bound to the carrier it
        # needs to be returned manually.
        if hasattr(self.carrier, '__quma_conn__'):
            if force:
                del self.carrier.__quma_conn__
            else:
                return
        self.conn.put(self.raw_conn)

    def close(self):
        self.put(force=True)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def get_conn_attr(self, attr):
        return getattr(self.raw_conn, attr)

    def set_conn_attr(self, attr, value):
        setattr(self.raw_conn, attr, value)

    def __getattr__(self, attr):
        try:
            return getattr(self.raw_cursor, attr)
        except AttributeError:
            pass
        try:
            return CursorNamespace(get_namespace(self, attr), self)
        except AttributeError:
            raise AttributeError('Namespace, Root method, or cursor '
                                 f'attribute "{attr}" not found.')


class DatabaseCallWrapper(object):
    def __init__(self, database, carrier, autocommit):
        self.database = database
        self.carrier = carrier
        self.autocommit = autocommit

    @property
    def cursor(self):
        return Cursor(self.database.conn,
                      self.database.namespaces,
                      self.database.contextcommit,
                      carrier=self.carrier,
                      autocommit=self.autocommit)


class Database(object):
    DoesNotExistError = exc.DoesNotExistError
    MultipleRecordsError = exc.MultipleRecordsError

    def __init__(self, dburi, *args, **kwargs):
        # if the second arg is present it must be sqldirs
        if args and len(args) > 1:
            raise ValueError('Max number of arguments is two')
        elif args and len(args) == 1:
            self.sqldirs = args[0]
        else:
            self.sqldirs = kwargs.pop('sqldirs', [])

        self.file_ext = kwargs.pop('file_ext', 'sql')
        self.tmpl_ext = kwargs.pop('tmpl_ext', 'msql')
        self.query_factory = kwargs.pop('query_factory', Query)
        self.prepare_params = kwargs.pop('prepare_params', None)
        self.contextcommit = kwargs.pop('contextcommit', False)
        self.show = kwargs.pop('show', False)
        self.cache = kwargs.pop('cache', False)

        # The remaining kwargs are passed to the DBAPI connect call
        self.conn = connect(dburi, **kwargs)

        self.namespaces = {}

        try:
            # A single directory
            self.register_namespace(self.sqldirs)
        except TypeError:
            # A list/collection of directories
            for sqldir in self.sqldirs:
                self.register_namespace(sqldir)

    def __call__(self, carrier=None, autocommit=False):
        return DatabaseCallWrapper(self, carrier=carrier,
                                   autocommit=autocommit)

    def register_namespace(self, sqldir):
        def instantiate(ns, ns_class, path):
            if ns in self.namespaces:
                # pass the old namespace to the new instance
                shadow = self.namespaces[ns]
                self.namespaces[ns] = ns_class(self, path, shadow=shadow)
            else:
                self.namespaces[ns] = ns_class(self, path)

        def register(path, ns):
            try:
                mod_path = str(path / '__init__.py')
                mod_name = f'quma.mapping.{ns}'
                module = SourceFileLoader(mod_name, mod_path).load_module()
                if ns == '__root__':
                    class_name = 'Root'
                else:
                    # snake_case to CamelCase
                    class_name = ''.join([s.title() for s in ns.split('_')])
                ns_class = getattr(module, class_name)
                if hasattr(ns_class, 'alias'):
                    instantiate(ns_class.alias, ns_class, path)
                instantiate(ns, ns_class, path)
            except (AttributeError, FileNotFoundError):
                instantiate(ns, Namespace, path)

        register(Path(sqldir), '__root__')
        for path in Path(sqldir).iterdir():
            if path.is_dir():
                register(path, path.name)

    def close(self):
        self.conn.close()
        self.conn = None

    def release(self, carrier):
        carrier.__quma_conn__.conn.put(carrier.__quma_conn__.raw_conn)
        del carrier.__quma_conn__

    def execute(self, sql, **kwargs):
        c = self.cursor()
        try:
            c.execute(sql, **kwargs)
            c.commit()
        except Exception as e:
            c.rollback()
            raise e
        return c

    @property
    def cursor(self):
        return Cursor(self.conn, self.namespaces, self.contextcommit)

    def __getattr__(self, attr):
        try:
            return get_namespace(self, attr)
        except AttributeError:
            raise AttributeError(f'Namespace or Root method "{attr}" '
                                 'not found.')


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
