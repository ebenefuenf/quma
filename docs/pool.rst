===============
Connection Pool
===============

quma provides a connection pool implementation (PostgreSQL and MySQL only)
similar to  `sqlalchemy's <https://www.sqlalchemy.org>`_ and even borrows 
code and ideas from it.

Setup a pool:

.. code-block:: python

    # PostgreSQL pool (keeps 5 connections open and allows 10 more)
    db = Database('postgresql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

    # MySQL/MariaDB pool 
    db = Database('mysql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

Additional initialization parameters:

* **size** (default 5) the size of the pool to be maintained. This is the
  largest number of connections that will be kept persistently in the
  pool. The pool begins with no connections.
* **overflow** (default 10) the maximum overflow size of the pool. When 
  the number of checked-out connections reaches the size set in `size`,
  additional connections will be returned up to this limit. Set to -1 
  to indicate no overflow limit.
* **timeout** (default None) the number of seconds to wait before giving
  up on returning a connection.

