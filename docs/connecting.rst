==========
Connecting
==========

`Database` initialization parameters:

::

    Database(dburi, sqldirs, persist=False, pessimistic=False, 
             file_ext='sql', tmpl_ext='msql', 
             show=False, cache=False)

* **dburi** the connection string. See section "Connection Examples"
* **sqldirs** one or more filesystem paths pointing to the sql scripts.
* **persist** (default False) if True **quma** immediately opens a 
  connection and keeps it open througout the complete application run time.
  Setting it to True will raise an error if you try to initialize a 
  connection pool.
* **pessimistic** (default False) if True *quma* emits a test statement on 
  a persistent SQL connection every time it is accessed or at the start of
  each connection pool checkout (see section "Connection Pool"), to test 
  that the database connection is still viable.
* **file_ext** (default 'sql') the file extension of sql files
* **tmpl_ext** (default 'msql') the file extension of template files 
  (see section "Templates").
* **show** (default False) print the executed query to stdout if True
* **cache** (default False) cache the queries in memory if True. 
  Other wise re-read each script when the query is executed.


Connection Examples
-------------------

.. code-block:: python

    sqldir = '/path/to/sql/scripts'

    # SQLite
    db = Database('sqlite:////path/to/db.sqlite', sqldir)
    # SQLite in memory db
    db = Database('sqlite:///', sqldir)

    # PostgreSQL localhost
    db = Database('postgresql://username:password@/db_name', sqldir)
    # PostgreSQL network server
    db = Database('postgresql://username:password@192.168.1.1:5432/db_name', sqldir)

    # MySQL/MariaDB localhost
    db = Database('mysql://username:password@/db_name', sqldir)
    # MySQL/MariaDB network server
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', sqldir)

