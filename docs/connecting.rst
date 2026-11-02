==========
Connecting
==========

You connect to a server/database by creating an instance of the class 
:class:`quma.Database`. You have to at least provide a valid
database URL and the path to your sql scripts. See below for the 
details.


Connection Examples
-------------------

.. code-block:: python

    sqldirs = '/path/to/sql/scripts'

    # can also be a list of paths:
    sqldirs = [
      '/path/to/sql/scripts',
      '/another/path/to/sql/scripts',
    ]

    # SQLite
    db = Database('sqlite3:////path/to/db.sqlite', sqldirs)
    # SQLite in memory db
    db = Database('sqlite3:///:memory:', sqldirs)

    # PostgreSQL with psycopg 3, localhost
    db = Database('psycopg://username:password@/db_name', sqldirs)
    # PostgreSQL with psycopg 3, network server
    db = Database('psycopg://username:password@10.0.0.1:5432/db_name', sqldirs)
    # PostgreSQL with psycopg2
    db = Database('psycopg2://username:password@/db_name', sqldirs)

    # MySQL/MariaDB localhost
    db = Database('mysqlclient://username:password@/db_name', sqldirs)
    # MySQL/MariaDB network server
    db = Database('mysqlclient://username:password@192.168.1.1:3306/db_name', sqldirs)

    # You can pass driver specific parameters e. g. MySQL's charset
    db = Database('mysqlclient://username:password@192.168.1.1:3306/db_name', 
                  sqldirs, 
                  charset='utf8')

Drivers
-------

The scheme of the URL names the package of the database driver:

* ``sqlite3://``: Python's built-in :mod:`sqlite3` module
* ``psycopg://``: `psycopg 3 <https://www.psycopg.org/psycopg3/>`_
  (PostgreSQL)
* ``psycopg2://``: `psycopg2 <https://www.psycopg.org/docs/>`_ (PostgreSQL)
* ``mysqlclient://``: `mysqlclient <https://github.com/PyMySQL/mysqlclient>`_
  (MySQL/MariaDB)
* ``asyncmy://``: `asyncmy <https://github.com/long2ice/asyncmy>`_
  (MySQL/MariaDB), for the :doc:`async API <async>` only
* ``aiosqlite://``: `aiosqlite <https://github.com/omnilib/aiosqlite>`_
  (SQLite), for the :doc:`async API <async>` only

Append ``+pool`` to the scheme to use a :doc:`connection pool <pool>`, e.g.
``psycopg+pool://``.

.. _on-connect:

Setting up new connections
--------------------------

Pass ``on_connect`` to run a function on every connection quma opens, with every
driver and with or without a pool. It receives the raw driver connection, so it is
the place for setup that needs the connection itself:

.. code-block:: python

    from pgvector.psycopg import register_vector

    def setup(conn):
        register_vector(conn)
        with conn.cursor() as cur:
            cur.execute("SET search_path = app, public")

    db = Database('psycopg+pool://username:password@/db_name', sqldirs,
                  on_connect=setup)

* It runs when a connection opens, not at each checkout from a pool. Without a pool
  or ``persist=True`` every cursor opens a connection, so it runs for every cursor.
* quma commits after it returns. So a ``SET`` stays in effect, which a rollback would
  undo on PostgreSQL, and anything it writes is permanent.
* It runs before a cursor's ``autocommit`` applies, so it starts in the same state
  either way.
* If it raises, quma closes the connection and passes the exception on. Driver errors
  become :doc:`quma's exceptions <errors>`.
* Its statements use the raw connection, so ``on_execute`` and the ``quma`` logger
  don't report them, and their placeholders are the driver's.

:class:`quma.AsyncDatabase` takes a plain or an async function:

.. code-block:: python

    from pgvector.psycopg import register_vector_async

    async def setup(conn):
        await register_vector_async(conn)

    db = AsyncDatabase('psycopg+pool://username:password@/db_name', sqldirs,
                       on_connect=setup)

:class:`quma.Database` raises ``TypeError`` for an async function.

PostgreSQL drivers
------------------

quma aims to behave the same with psycopg 3 and psycopg2, so the same SQL
scripts work with either of them:

* psycopg 3 uses client-side parameter binding like psycopg2
  (:class:`psycopg.ClientCursor`).
* If a script contains multiple statements, the cursor exposes the result
  of the last one, as psycopg2 does.
* Rows support access by index and key, and by attribute when using
  ``changeling``.

Values are still adapted by the driver in use. psycopg 3 differs from
psycopg2 for example in how it adapts tuples and ranges (see `Differences
from psycopg2 <https://www.psycopg.org/psycopg3/docs/basic/from_pg2.html>`_),
and its cursors have no ``lastrowid``.


The Database class
------------------

.. autoclass:: quma.database.Database
    :members:
