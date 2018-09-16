from functools import partial
from importlib import import_module
from importlib.machinery import SourceFileLoader
from itertools import chain
from pathlib import Path
from urllib.parse import urlparse

from . import exc
from . import pool

try:
    from mako.template import Template
except ImportError:  # pragma: no cover
    Template = None


class CursorWrapper(object):
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
    def __init__(self, conn, carrier=None):
        self.conn = conn
        self.carrier = carrier
        self.raw_conn = None
        self.raw_cursor = None

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
                self.raw_conn = self.carrier._quma_conn
            else:
                self.raw_conn = self.carrier._quma_conn = self.conn.get()
        else:
            self.raw_conn = self.conn.get()
        self.raw_cursor = CursorWrapper(self.conn,
                                        self.conn.cursor(self.raw_conn))
        return self

    def put(self):
        """
        Ensures that not only the cursor is closed but also
        the connection if necessary.
        """
        self.raw_cursor.close()

        # If the connection is bound to the carrier it
        # needs to be returned manually.
        if not hasattr(self.carrier, '_quma_conn'):
            self.conn.put(self.raw_conn)

    def close(self):
        self.put()

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

    def _fetch(self, func):
        try:
            return func()
        except exc.FetchError as e:  # pragma: no cover
            raise e.error

    def __call__(self, cursor, *args, **kwargs):
        self._execute(cursor, list(args), kwargs)
        return self._fetch(cursor.fetchall)

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
                raise ImportError(
                    'To use templates you need to install Mako')
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

    def many(self, cursor, size=None, *args, **kwargs):
        if size is None:
            size = cursor.arraysize
        self._execute(cursor, list(args), kwargs)
        return self._fetch(partial(cursor.fetchmany, size))

    def next(self, cursor, size=None):
        if size is None:
            size = cursor.arraysize
        return self._fetch(partial(cursor.fetchmany, size))


class Namespace(object):
    def __init__(self, db, sqldir, shadow=None):
        self.db = db
        self.sqldir = sqldir
        self.cache = db.cache
        self.show = db.show
        self.shadow = shadow
        self._queries = {}
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
                    init_params=self.db.init_params)

    def __getattr__(self, attr):
        if self.cache:
            try:
                return self._queries[attr]
            except AttributeError:
                return getattr(self.shadow, attr)

        if attr.startswith('_'):
            # unshadow - see collect_queries
            attr = attr[1:]

        try:
            sqlfile = self.sqldir / f'{attr}.{self.db.file_ext}'
            if not sqlfile.is_file():
                sqlfile = self.sqldir / f'{attr}.{self.db.tmpl_ext}'
            with open(sqlfile, 'r') as f:
                return self.db.query_factory(
                    f.read(),
                    self.show,
                    Path(sqlfile).suffix == f'.{self.db.tmpl_ext}',
                    init_params=self.db.init_params)
        except FileNotFoundError:
            return getattr(self.shadow, attr)


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

        self.file_ext = kwargs.pop('file_ext', 'sql')
        self.tmpl_ext = kwargs.pop('tmpl_ext', 'msql')
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
        if attr in self.namespaces:
            return self.namespaces[attr]

        root = self.namespaces['__root__']
        while root:
            try:
                return getattr(root, attr)
            except AttributeError:
                root = root.shadow
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
