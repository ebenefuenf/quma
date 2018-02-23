from itertools import chain
from pathlib import Path

from . import exc

try:
    from mako.template import Template
except ImportError:
    Template = None


class Query(object):
    def __init__(self, query, show, is_template, context_callback=None):
        self.show = show
        self.query = query
        self.context_callback = context_callback
        self.is_template = is_template
        self.context = None

    def __call__(self, cursor, returning=False, **kwargs):
        self._execute(cursor, kwargs)
        if returning:
            return cursor.fetchone()[0]

    def __str__(self):
        return self.query

    def print_sql(self, cursor):
        if cursor.query:
            print('-' * 50)
            print(cursor.query.decode('utf-8'))

    def prepare(self, cursor, kwargs):
        context = {}

        if self.context_callback:
            context = self.context_callback(cursor.request, context)

        context.update(kwargs)

        if self.is_template:
            try:
                return Template(self.query).render(**context), context
            except TypeError:
                raise Exception(
                    'To use templates (*.msql) you need to install Mako')
        return self.query, context

    def _execute(self, cursor, kwargs):
        query, context = self.prepare(cursor, kwargs)
        cursor.execute(query, context)

    def get(self, cursor, **kwargs):
        try:
            self._execute(cursor, kwargs)
        finally:
            self.show and self.print_sql(cursor)
        rowcount = cursor.rowcount
        if rowcount == 0:
            raise exc.DoesNotExistError()
        if rowcount > 1:
            raise exc.MultipleRecordsError()
        return cursor.fetchone()

    def all(self, cursor, **kwargs):
        try:
            self._execute(cursor, kwargs)
        finally:
            self.show and self.print_sql(cursor)
        return cursor.fetchall()

    def many(self, cursor, size, **kwargs):
        try:
            self._execute(cursor, kwargs)
        finally:
            self.show and self.print_sql(cursor)
        return cursor.fetchmany(size)

    def count(self, cursor, **kwargs):
        self._execute(cursor, kwargs)
        return cursor.rowcount


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
        if attr not in cls.ns:
            raise AttributeError()
        return cls.ns[attr]


class db(object, metaclass=Database):
    ns = {}
    context_callback = None

    def __init__(self, carrier=None):
        self.carrier = carrier

    @classmethod
    def register_namespace(cls, sqldir):
        for path in Path(sqldir).iterdir():
            if path.is_dir():
                cls.ns[path.name] = Namespace(cls, path)

    @classmethod
    def init(cls, connection, sqldirs, cache=True, show=False,
             context_callback=None):
        cls.ns = {}
        cls.connection = connection
        cls.cache = cache
        cls.show = show
        cls.context_callback = context_callback
        for sqldir in sqldirs:
            cls.register_namespace(sqldir)
