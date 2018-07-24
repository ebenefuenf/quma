# Portions of this module have been copied and modified from SQLAlchemy's
# pool module and is copyrighted by Michael Bayer under the terms of the
# MIT license. https://www.sqlalchemy.org/

import threading
from queue import (
    Queue as BaseQueue,
    Full,
    Empty,
)

from .core import Connection


class TimeoutError(Exception):
    """Raised when a connection pool times out on getting a connection."""


class Queue(BaseQueue):
    '''Create a queue object with a given maximum size.

    If maxsize is <= 0, the queue size is infinite.
    '''

    def __init__(self, maxsize=0):
        """ Overrides BaseQueue.__init__ to use a RLock instead of Lock"""

        self.maxsize = maxsize
        self._init(maxsize)
        self.mutex = threading.RLock()
        self.not_full = threading.Condition(self.mutex)
        self.not_empty = threading.Condition(self.mutex)
        self.all_tasks_done = threading.Condition(self.mutex)
        self.unfinished_tasks = 0


class Pool(object):
    """ A queuing pool of connections """

    def __init__(self, conn: Connection, size=5, overflow=10,
                 timeout=None) -> None:
        if conn.persist:
            raise ValueError('Persistent connections are not allowed')
        self._MAX = overflow
        self._overflow = 0 - size
        self._timeout = timeout
        self._overflow_lock = threading.Lock()
        self._pool = Queue(maxsize=size)
        self._conn = conn

    def _inc_overflow(self):
        if self._MAX == -1:
            self._overflow += 1
            return True
        with self._overflow_lock:
            if self._overflow < self._MAX:
                self._overflow += 1
                return True
            else:
                return False

    def _dec_overflow(self):
        if self._MAX == -1:
            self._overflow -= 1
            return True
        with self._overflow_lock:
            self._overflow -= 1
            return True

    def put(self, conn):
        try:
            self._pool.put(conn, False)
        except Full:
            try:
                conn.close()
            finally:
                self._dec_overflow()

    def get(self):
        use_overflow = self._MAX > -1

        try:
            wait = use_overflow and self._overflow >= self._MAX
            return self._pool.get(wait, self._timeout)
        except Empty:
            # don't do things inside of "except Empty", because when we say
            # we timed out or can't connect and raise, Python 3 tells
            # people the real error is queue.Empty which it isn't.
            pass
        if use_overflow and self._overflow >= self._MAX:
            if not wait:
                return self.get()
            else:
                raise TimeoutError(
                    "QueuePool limit of size %d overflow %d reached, "
                    "connection timed out, timeout %d" %
                    (self.size(), self.overflow(), self._timeout), code="3o7r")

        if self._inc_overflow():
            try:
                return self._conn.get()
            except Exception as e:
                self._dec_overflow()
                raise e
        else:
            return self.get()

    def close(self):
        while True:
            try:
                conn = self._pool.get(False)
                conn.close()
            except Empty:
                break

        self._overflow = 0 - self.size

    def status(self):
        return "Pool size: %d  Connections in pool: %d "\
            "Current Overflow: %d Current Checked out "\
            "connections: %d" % (self.size,
                                 self.checkedin,
                                 self.overflow,
                                 self.checkedout)

    @property
    def size(self):
        return self._pool.maxsize

    @property
    def checkedin(self):
        return self._pool.qsize()

    @property
    def overflow(self):
        return self._overflow

    @property
    def checkedout(self):
        return self._pool.maxsize - self._pool.qsize() + self._overflow