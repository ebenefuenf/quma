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
from .script import Script


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
    """
    The database object acts as the central object of the
    library.

    :param dburi: The connection string. See section "Connection Examples"
    :param sqldirs: One or more filesystem paths pointing to the sql scripts.
                    str or pathlib.Path.
    :param persist: If True quma immediately opens a
        connection and keeps it open throughout the complete application
        runtime. Setting it to True will raise an error if you try to
        initialize a connection pool. Defaults to false.
    :param pessimistic: If True quma emits a test statement on
        a persistent SQL connection every time it is accessed or at the start
        of each connection pool checkout (see section "Connection Pool"), to
        test that the database connection is still viable. Defaults to False.
    :param contextcommit: If True and a context manager is used quma will
        automatically commit all changes when the context manager exits.
        Defaults to False.
    :param prepare_params: A callback function which will be called before
        every query to prepare the params which will be passed to the query.
        Defaults to None.
    :param file_ext: The file extension of sql files. Defaults to 'sql'.
    :param tmpl_ext: The file extension of template files (see
        :doc:`Templates <templates>`). Defaults to 'msql'.
    :param show: Print the executed query to stdout if True. Defaults to False.
    :param cache: cache the scripts in memory if True,
        otherwise re-read each script when the query is executed.
        Defaults to False.

    Additional connection pool parameters (see :doc:`Connection pool <pool>`):

    :param size: The size of the pool to be maintained. This is the
        largest number of connections that will be kept persistently in the
        pool. The pool begins with no connections. Defaults to 5.
    :param overflow: The maximum overflow size of the pool. When
        the number of checked-out connections reaches the size set in `size`,
        additional connections will be returned up to this limit. Set to -1
        to indicate no overflow limit. Defaults to 10.
    :param timeout: The number of seconds to wait before giving
        up on returning a connection. Defaults to None.
    """
    DoesNotExistError = exc.DoesNotExistError
    MultipleRowsError = exc.MultipleRowsError

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
        self.script_factory = kwargs.pop('script_factory', Script)
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

    def execute(self, query, **kwargs):
        """Execute the statements in ``query`` and commit
        immediately.

        :param query: The sql query to execute.
        """
        result = None
        cur = self.cursor()
        try:
            cur.execute(query, **kwargs)
            cur.commit()
            if cur.description:
                result = cur.fetchall()
        except Exception as e:
            cur.rollback()
            raise e
        return result

    def close(self):
        """Close (all) open connections. If you want to reconnect you
        need to create a new :class:`quma.Database` instance.
        """
        self.conn.close()
        self.conn = None

    def release(self, carrier):
        """If the ``carrier`` holds a connection close it or return
        it to the pool.

        :param carrier: An object holding a quma connection. See
            :doc:`Reusing connections <carrier>`
        """
        if hasattr(carrier, '__quma_conn__'):
            carrier.__quma_conn__.conn.put(carrier.__quma_conn__.raw_conn)
            del carrier.__quma_conn__

    @property
    def cursor(self):
        """Open a connection and return a cursor."""
        return Cursor(self.conn, self.namespaces, self.contextcommit)

    def __getattr__(self, attr):
        try:
            return get_namespace(self, attr)
        except AttributeError:
            msg = 'Namespace or Root method "{}" not found.'.format(attr)
            raise AttributeError(msg)


def connect(dburi, **kwargs):
    """
    Create and return a Connection or Pool object specified
    via ``dburi`` (a string in the form of an URL)
    """
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
