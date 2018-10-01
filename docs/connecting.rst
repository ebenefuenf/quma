==========
Connecting
==========

You connect to a Server by creating an instance of the class 
:class:`quma.Database`. You have to at least provide a valid
database URL and the path to your sql scripts. See below for the 
details.


Connection Examples
-------------------

.. code-block:: python

    sqldir = '/path/to/sql/scripts'

    # SQLite
    db = Database('sqlite:////path/to/db.sqlite', sqldir)
    # SQLite in memory db
    db = Database('sqlite:///:memory:', sqldir)

    # PostgreSQL localhost
    db = Database('postgresql://username:password@/db_name', sqldir)
    # PostgreSQL network server
    db = Database('postgresql://username:password@10.0.0.1:5432/db_name', sqldir)

    # MySQL/MariaDB localhost
    db = Database('mysql://username:password@/db_name', sqldir)
    # MySQL/MariaDB network server
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', sqldir)


The Database class
------------------

.. autoclass:: quma.database.Database
    :members:
