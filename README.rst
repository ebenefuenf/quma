****
quma
****

A simple **Python** >= v3.5 and **SQLite**/**PostgreSQL**/**MySQL**/**MariaDB** library 
which maps methods to SQL scripts. Unlike ORMs, it allows to write SQL as
it was intented and to use all featuers the DBMS provides.

Installation
============

Download the git repository and run ``python setup.py install``.

Development: ``pip install -e '.[test,templates,postgres,mysql]'``

If you like to use SQLite, Python has everything covered. To use PostgreSQL
you need to install *psycopg2* or *psycopg2cffi*. For MySQL/MariaDB it's *mysqlclient*.

If you want to use templates install *mako*.


Usage
=====

Given a directory with some SQL scripts:

::

    /home/user/sql-scripts
    ├── users
    │    ├── all.sql
    │    ├── by_city.sql
    │    ├── by_id.sql
    │    ├── rename.sql
    │    └── remove.sql
    └── get_admin.sql
    
**Via Context Manager:**

.. code-block:: python

    from quma import (
        Database,
        DoesNotExistError, 
        MultipleRecordsError,
    )

    db = Database('postgresql://user:pw@/database', 
                  '/path/to/sql-scripts')

    # Run a SQL statement. Commits every call.
    db.execute('CREATE TABLE users ...')

    with db.cursor as c:
        # get multiple records
        all_users = db.users.all(c)
        for user in all_users:
            print(user['name'])


        # get data in chunks (fetchmany)
        #
        # the first two
        users = db.users.by_city.many(c, 2, city='City')
        # the next three
        users = db.users.by_city.next(c, 3)
        # the next two
        users = db.users.by_city.next(c, 2)


        # get a single item
        try:
            user = db.users.by_id.get(c, id=13)
        except DoesNotExistError:
            print('The user does not exist')
        except MultipleRecordsError:
            print('There are multiple users with the same id')

        # multiple changes and commit 
        db.users.remove(c, id=user['id'])
        db.users.rename(c, id=14, name='New Name')
        c.commit()

        # call the root level script
        admin = db.get_admin(c)

**Without:**

.. code-block:: python

    from quma import Database

    db = Database('sqlite:////path/to/db.sqlite', '/path/to/sql-scripts')

    try:
        c = db.cursor()
        db.users.remove(c, user.id)
        c.commit()
    finally:
        c.close()

`Database` initialization parameters:

::

    Database(dburi, sqldirs, file_ext='sql', tmpl_ext='msql', 
            show=False, cache=False)

* **dburi** the connection string. See section "Connection Examples"
* **sqldirs** one or more filesystem paths pointing to the sql scripts.
* **file_ext** (default 'sql') the file extension of sql files
* **tmpl_ext** (default 'msql') the file extension of template files 
  (see section "Templates").
* **show** (default False) print the executed query to stdout if True
* **cache** (default False) cache the queries in memory if True. Other
  wise re-read each script when the query is executed.


Connection Examples
-------------------

.. code-block:: python

    sqldir = '/path/to/sql-scripts'

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

Connection Pool
---------------

*quma* supports a connection pool (PostgreSQL and MySQL only) like 
*`sqlalchemy <https://www.sqlalchemy.org>`* and even borrows some
code and ideas from it.

Setup a pool:

.. code-block:: python

    # PostgreSQL pool (keeps 5 connections open and allows 10 more)
    db = Database('postgresql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)
    # MySQL/MariaDB pool 
    db = Database('mysql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

Initialization parameters:

* all general parameters. See "Usage"
* **size** (default 5) the size of the pool to be maintained. This is the
  largest number of connections that will be kept persistently in the
  pool. The pool begins with no connections.
* **overflow** (default 10) the maximum overflow size of the pool. When 
  the number of checked-out connections reaches the size set in `size`,
  additional connections will be returned up to this limit.
* **timeout** (default None) the number of seconds to wait before giving
  up on returning a connection.
* **pessimistic** (default False) if True *quma* emits a test statement on 
  the SQL connection at the start of each connection pool checkout, 
  to test that the database connection is still viable.

Reusing connections
-------------------

To reuse connections you can pass a carrier object to `db`. *quma* then
creates the attribute `__quma_conn__` on the carrier holding the 
connection object. You should only use this feature if this fact doesn't
lead to problems in your application. A good example is the request
object in web applications:

.. code-block:: python

    from pyramid.view import view_config
    from quma import Database

    db = Database('sqlite:////path/to/db.sqlite', sqldir)


    def do_more(request, user_id):
        # reuses the same connection which was opened
        # in user_view.
        with db(request).cursor as c:
            db.user.remove(c, id=user_id)


    @view_config(route_name='user')
    def user_view(request):
        with db(request).cursor as c:
            user = db.user.by_name(c, name='Username')
            do_more(request, user.id)
            c.commit()

Changling Cursor
----------------

If you are using **SQLite** or **PostgreSQL** you can access result 
object attributes by three different methods if you pass 
``changling=True`` on db initialization. (MySQL does not support it. See below)

.. code-block:: python

    db = Database('sqlite:///', sqldir, changeling=True)

    with db.cursor as c:
        user = db.users.by_id.get(c, 13)
        name = user[0]       # by index
        name = user['name']  # by key
        name = user.name     # by attribute

By default changling is *False* which is slightly faster. Then SQLite 
supports access by index only. PostgreSQL by key and index (we use 
*psycopg.extras.DictCursor* internally).

MySQL/MariaDB supports access by index only, except you pass 
``dict_cursor=True`` on initialization. Then it supports access by 
key only.

Passing Parameters to SQL Queries
---------------------------------

SQLite supports two kinds of placeholders: question marks (*qmark* style)
and named placeholders (named style). PostgreSQL/MySQL/MariaDB support 
simple (`%s`) and named (`%(name)s`) *pyformat* placeholders:

.. code-block:: sql

    -- SQLite qmark
    SELECT name, email FROM users WHERE id = ?
    -- named
    SELECT name, email FROM users WHERE id = :id

    -- PostgreSQL/MySQL/MariaDB pyformat
    SELECT name, email FROM users WHERE id = %s
    -- named
    SELECT name, email FROM users WHERE id = %(id)s

.. code-block:: python

    # simple style (? or %s)
    db.users.by_id.get(c, 1)
    # named style (:name or %(name)s)
    db.users.by_id.get(c, id=1)

Templates
---------

*quma* supports SQL script templates using the
`Mako template library <http://www.makotemplates.org>`. By default
template files must have the file extension `msql` 
(can be overwritten). Using this feature you can write dynamic
queries which would not be possible with SQL alone. 
**Beware of SQL injections**.

Example:

.. code-block:: sql

    -- sql/users/by_group.msql
    SELECT
        name,
    % if admin:
        birthday,
    % endif
        city
    FROM users
    WHERE 
    % if admin:
        group IN ('admins', %(group)s)
    % else:
        group = %(group)s
    % endif

.. code-block:: python

    db.users.by_group(c, admin=True, group='public')
        

Testing
=======

**Prerequisites**: In order to run the tests for *MySQL* or *PostgreSQL*
you need to create a test database:

PostgreSQL:

.. code-block:: sql

    CREATE USER quma_test_user WITH PASSWORD 'quma_test_password';
    CREATE DATABASE quma_test_db;
    GRANT ALL PRIVILEGES ON DATABASE quma_test_db to quma_test_user;

MySQL/MariaDB:

.. code-block:: sql

    CREATE DATABASE quma_test_db;
    CREATE USER quma_test_user@localhost IDENTIFIED BY 'quma_test_password';
    GRANT ALL ON quma_test_db.* TO quma_test_user@localhost;

How to run the tests
--------------------

Run ``pytest`` or ``py.test`` to run all tests. 
``pytest -m "not postgres and not mysql"`` for all general 
tests. And ``pytest -m "postgres"`` or ``pytest -m "mysql"`` 
for DBMS specific tests.
