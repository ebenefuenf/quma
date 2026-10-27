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
    db = Database('sqlite:////path/to/db.sqlite', sqldirs)
    # SQLite in memory db
    db = Database('sqlite:///:memory:', sqldirs)

    # PostgreSQL with psycopg 3, localhost
    db = Database('psycopg://username:password@/db_name', sqldirs)
    # PostgreSQL with psycopg 3, network server
    db = Database('psycopg://username:password@10.0.0.1:5432/db_name', sqldirs)
    # PostgreSQL with psycopg2
    db = Database('psycopg2://username:password@/db_name', sqldirs)

    # MySQL/MariaDB localhost
    db = Database('mysql://username:password@/db_name', sqldirs)
    # MySQL/MariaDB network server
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', sqldirs)

    # You can pass driver specific parameters e. g. MySQL's charset
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', 
                  sqldirs, 
                  charset='utf8')

PostgreSQL drivers
------------------

For PostgreSQL the scheme names the driver: ``psycopg://`` uses
`psycopg 3 <https://www.psycopg.org/psycopg3/>`_ and ``psycopg2://`` uses
`psycopg2 <https://www.psycopg.org/docs/>`_. ``postgresql://`` is an alias
for ``psycopg2://``.

quma aims to behave the same with both drivers, so the same SQL scripts work
with either of them:

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
