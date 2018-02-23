from pathlib import Path


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
    def register_namespace(cls, script_dir):
        for path in Path(script_dir).iterdir():
            if path.is_dir():
                cls.ns[path.name] = [p for p in path.glob('*.sql')]

    @classmethod
    def init(cls, connection, script_dirs, cache=True, show=False,
             context_callback=None):
        cls.ns = {}
        cls.connection = connection
        cls.cache = cache
        cls.show = show
        cls.context_callback = context_callback
        for script_dir in script_dirs:
            cls.register_namespace(script_dir)
