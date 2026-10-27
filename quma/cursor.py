from . import exc
from .namespace import (
    CursorNamespace,
    get_namespace,
)
from .query import Query
from .script import Script


class CarriedConnection:
    def __init__(self, conn, raw_conn):
        self.conn = conn
        self.raw_conn = raw_conn


class RawCursorWrapper:
    def __init__(self, conn, raw_cursor):
        self.conn = conn
        self.cursor = raw_cursor
        self.has_rowcount = conn.has_rowcount

    def __getattr__(self, key):
        return self.conn.get_cursor_attr(self.cursor, key)


class Cursor:
    def __init__(
        self, db, namespaces, contextcommit, carrier=None, autocommit=False
    ):
        self.db = db
        self.conn = db.conn
        self.namespaces = namespaces
        self.carrier = carrier
        self.autocommit = isinstance(autocommit, bool) and autocommit
        self.raw_conn = None
        self.raw_cursor = None
        self.contextcommit = contextcommit

    def __enter__(self):
        return self.create_cursor()

    def __exit__(self, *args):
        if self.raw_conn is None:
            return
        if self.contextcommit:
            self.commit()
        if self.conn:
            self.put()

    def __call__(self, autocommit=False):
        return self.create_cursor(autocommit=autocommit)

    def create_cursor(self, autocommit=False):
        autocommit = (
            True
            if isinstance(autocommit, bool) and autocommit
            else self.autocommit
        )
        if self.carrier:
            if self.carrier.conn:
                self.raw_conn = self.carrier.conn.raw_conn
            else:
                raw_conn = self.conn.get(autocommit=autocommit)
                self.carrier.add_conn(CarriedConnection(self.conn, raw_conn))
                self.raw_conn = raw_conn
        else:
            self.raw_conn = self.conn.get(autocommit=autocommit)
        self.raw_cursor = RawCursorWrapper(
            self.conn, self.conn.cursor(self.raw_conn)
        )
        return self

    def put(self, force=False):
        """
        Ensures that not only the cursor is closed but also
        the connection if necessary.

        If the connection is bound to the carrier it
        needs to be returned manually.

        If :param:`force` is set to True return is anyway
        """
        if self.raw_conn is None or self.raw_cursor is None:
            return
        self.raw_cursor.close()

        if self.carrier and self.carrier.conn:
            if not force:
                return
            self.carrier.release()
            self.carrier = None
        else:
            self.conn.put(self.raw_conn)
        self.raw_conn = None

    def close(self):
        self.put(force=True)

    def commit(self):
        self._open_conn().commit()

    def rollback(self):
        self._open_conn().rollback()

    def _open_conn(self):
        if self.raw_conn is None:
            raise exc.APIError("The cursor has no open connection.")
        return self.raw_conn

    def query(self, content, *args, is_template=False, **kwargs):
        """
        Creates an ad hoc Query object based on content.
        """
        script = Script(
            content,
            self.db.echo,
            is_template,
            self.db.sqldirs,
            self.db.prepare_params,
        )
        return Query(script, self, args, kwargs, self.db.prepare_params)

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
        except AttributeError as e:
            raise AttributeError(
                "Namespace, Root method, or cursor "
                f'attribute "{attr}" not found.'
            ) from e
