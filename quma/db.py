from itertools import chain
from pathlib import Path


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

            if hasattr(self, attr):
                # We have real namespace method which shadows
                # this file
                attr = f'_{attr}'

            with open(sqlfile, 'r') as f:
                self._queries[attr] = f.read()

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
            return f.read()


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
