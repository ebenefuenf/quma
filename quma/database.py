from importlib import import_module
from importlib.machinery import SourceFileLoader
from pathlib import Path
from urllib.parse import urlparse

from . import (
    exc,
    pool,
)
from .cursor import Cursor
from .namespace import (
    Namespace,
    get_namespace,
)
from .query import Query


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
            if issubclass(type(self.sqldirs), Path):
                self.sqldirs = str(self.sqldirs)
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
                mod_name = 'quma.mapping.{}'.format(ns)
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
        if hasattr(carrier, '__quma_conn__'):
            carrier.__quma_conn__.conn.put(carrier.__quma_conn__.raw_conn)
            del carrier.__quma_conn__

    def execute(self, sql, **kwargs):
        result = None
        cur = self.cursor()
        try:
            cur.execute(sql, **kwargs)
            cur.commit()
            if cur.description:
                result = cur.fetchall()
        except Exception as e:
            cur.rollback()
            raise e
        return result

    @property
    def cursor(self):
        return Cursor(self.conn, self.namespaces, self.contextcommit)

    def __getattr__(self, attr):
        try:
            return get_namespace(self, attr)
        except AttributeError:
            msg = 'Namespace or Root method "{}" not found.'.format(attr)
            raise AttributeError(msg)


def connect(dburi, **kwargs):
    url = urlparse(dburi)
    scheme = url.scheme.split('+')
    module_name = scheme[0]
    module = import_module('quma.provider.{}'.format(module_name))
    conn = getattr(module, 'Connection')(url, **kwargs)
    try:
        if scheme[1].lower() == 'pool':
            return pool.Pool(conn, **kwargs)
        else:
            raise ValueError('Wrong scheme. Only "provider://" or '
                             '"provider+pool://" are allowed')
    except IndexError:
        return conn
