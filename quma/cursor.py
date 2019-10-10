from .namespace import (
    CursorNamespace,
    get_namespace,
)
from .query import Query
from .script import Script


class CarriedConnection(object):
    def __init__(self, conn, raw_conn):
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper(object):
    def __init__(self, conn, raw_cursor):
        self.conn = conn
        self.cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key):
        try:
            return self.conn.get_cursor_attr(self.cursor, key)
        except AttributeError as e:
            raise e


class Cursor(object):
    def __init__(self, db, namespaces, contextcommit,
                 carrier=None, autocommit=False):
        self.db = db
        self.conn = db.conn
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
        if self.conn:
            self.put()

    def __call__(self, autocommit=None):
        return self.create_cursor(autocommit=autocommit)

    def create_cursor(self, autocommit=None):
        autocommit = autocommit if autocommit is not None else self.autocommit
        if self.carrier:
            if self.carrier.conn:
                self.raw_conn = self.carrier.conn.raw_conn
            else:
                raw_conn = self.conn.get(autocommit=autocommit)
                self.carrier.add_conn(CarriedConnection(self.conn, raw_conn))
                self.raw_conn = raw_conn
        else:
            self.raw_conn = self.conn.get(autocommit=autocommit)
        self.raw_cursor = RawCursorWrapper(self.conn,
                                           self.conn.cursor(self.raw_conn))
        return self

    def put(self, force=False):
        """
        Ensures that not only the cursor is closed but also
        the connection if necessary.

        If the connection is bound to the carrier it
        needs to be returned manually.

        If :param:`force` is set to True return is anyway
        """
        self.raw_cursor.close()

        if self.carrier and self.carrier.conn:
            if not force:
                return
            self.carrier.release()
            self.carrier = None
            return
        self.conn.put(self.raw_conn)

    def close(self):
        self.put(force=True)

    def commit(self):
        self.raw_conn.commit()

    def rollback(self):
        self.raw_conn.rollback()

    def query(self, content, *args, is_template=False, **kwargs):
        """
        Creates an ad hoc Query object based on content.
        """
        script = Script(content, self.db.echo, is_template,
                        self.db.sqldirs, self.db.prepare_params)
        return Query(script, self, args, kwargs,
                     self.db.prepare_params)

    def get_conn_attr(self, attr):
        return getattr(self.raw_conn, attr)

    def set_conn_attr(self, attr, value):
        setattr(self.raw_conn, attr, value)

    def mogrify(self, content, params):
        return self.conn.mogrify(self.raw_cursor, content, params)

    def __getattr__(self, attr):
        try:
            return getattr(self.raw_cursor, attr)
        except AttributeError:
            pass
        try:
            return CursorNamespace(get_namespace(self, attr), self)
        except AttributeError:
            raise AttributeError('Namespace, Root method, or cursor '
                                 'attribute "{}" not found.'.format(attr))
