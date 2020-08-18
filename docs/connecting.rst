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

    # PostgreSQL localhost
    db = Database('postgresql://username:password@/db_name', sqldirs)
    # PostgreSQL network server
    db = Database('postgresql://username:password@10.0.0.1:5432/db_name', sqldirs)

    # MySQL/MariaDB localhost
    db = Database('mysql://username:password@/db_name', sqldirs)
    # MySQL/MariaDB network server
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', sqldirs)

    # You can pass driver specific parameters e. g. MySQL's charset
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', 
                  sqldirs, 
                  charset='utf8')


The Database class
------------------

.. autoclass:: quma.database.Database
    :members:
