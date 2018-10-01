===============
Connection pool
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

For a description of the parameters see :doc:`Connecting <connecting>`.
