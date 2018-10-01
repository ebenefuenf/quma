from .namespace import (
    CursorNamespace,
    get_namespace,
)


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
                                 'attribute "{}" not found.'.format(attr))
