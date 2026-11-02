===============
Connection pool
===============

quma provides a connection pool implementation (PostgreSQL and MySQL only)
similar to  `sqlalchemy's <https://www.sqlalchemy.org>`_ and even borrows 
code and ideas from it.

Setup a pool:

.. code-block:: python

    # PostgreSQL pool (keeps 5 connections open and allows 10 more)
    db = Database('psycopg+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

    # MySQL/MariaDB pool 
    db = Database('mysqlclient+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

For a description of the parameters see :doc:`Connecting <connecting>`.

Waiting for a connection
------------------------

When ``size`` and ``overflow`` are used up, a request waits for a connection to
come back. After ``timeout`` seconds, 30 by default, it gets
:class:`quma.TimeoutError`. ``timeout=None`` waits forever.

``timeout`` covers only the wait for a free connection. Opening a connection can
take longer and has its own setting in the driver, like ``connect_timeout`` on
PostgreSQL and MySQL.

``max_waiting`` limits how many requests may wait. Further ones get
:class:`quma.TooManyWaiting` at once, a subclass of :class:`quma.TimeoutError`, so
under overload they fail fast instead of piling up. With ``max_waiting=0`` nobody
waits. It's off by default, and it matters most with the :doc:`async API <async>`,
where waiting tasks are cheap and nothing else limits them. In a threaded server
each waiter already takes up a thread.

.. code-block:: python

    db = AsyncDatabase('psycopg+pool://username:password@/db_name', sqldir,
                       size=10, timeout=5, max_waiting=50)

Limiting how long connections live
----------------------------------

By default a connection stays in the pool until it breaks or the pool closes.
Two options replace connections earlier. Both are in seconds and off by default:

.. code-block:: python

    db = Database('psycopg+pool://username:password@/db_name', sqldir,
                  max_lifetime=3600, max_idle=600)

``max_lifetime``
    The age at which a connection is replaced. Set it below a limit outside
    your application, like a proxy that closes connections after an hour, or
    use it to reach a new server after a failover. Each connection gets a
    random lifetime of 95 to 100 percent of this value, so connections opened
    together don't all expire together.

``max_idle``
    How long a connection may stay unused in the pool. Set it below the idle
    timeout of a firewall or load balancer, or use it to give connections back
    to the server after a busy period. With this option the pool reuses the
    most recently returned connection first, because otherwise every connection
    keeps being used in turn and none reaches the limit.

The pool has no background thread or task. It closes expired connections when a
connection is checked out or returned, which means:

* A pool without traffic keeps its connections until the next checkout, which
  replaces them. Don't rely on ``max_idle`` to free connections during a
  quiet period.
* After a pool has shrunk or emptied, the next requests pay for opening new
  connections.
* A connection in use is never interrupted. If it passed ``max_lifetime``,
  it is closed when it is returned.
* A connection that dies before reaching a limit still raises
  :class:`quma.ConnectionLost` on its next statement. Use ``pessimistic=True``
  to test connections at checkout.
