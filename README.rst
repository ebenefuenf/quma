****
quma
****

A simple **Python** >= v3.5 and **SQLite**/**PostgreSQL**/**MySQL** library 
which maps methods to SQL scripts. Unlike ORMs, it allows to write SQL as
it was intented and to use all featuers the DBMS provides.

Installation
============

Download the git repository and run ``python setup.py install``.

Development: ``pip install -e '.[test,templates,postgres,mysql]'``

If you like to use SQLite, Python has everything covered. To use PostgreSQL
you need to install *psycopg2* or *psycopg2cffi*. For MySQL it's *mysqlclient*.

If you want to use templates install *mako*.


Usage
=====

Example:
--------

Given a directory with some SQL scripts:

::

    /home/user/sql-scripts
    ├── users
    │    ├── all.sql
    │    ├── by_id.sql
    │    ├── rename.sql
    │    └── remove.sql
    └── get_admin.sql
    
Python:

.. code-block:: python

    from quma import Database

    db = Database('sqlite:////path/to/db.sqlite', '/path/to/sql-scripts')

    with db.cursor as c:
        # get a list of records
        all_users = db.users.all(c)

        # get a single item
        user = db.users.by_id.get(c, 13)

        # multiple changes and commit 
        db.users.remove(c, user.id)
        db.users.rename(c, 14, 'New Name')
        c.commit()

        # access the root level script
        admin = db.get_admin(c)


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
    # PostgreSQL pool (keeps 5 connections open and allows 10 more)
    db = Database('postgresql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)

    # MySQL localhost
    db = Database('mysql://username:password@/db_name', sqldir)
    # MySQL network server
    db = Database('mysql://username:password@192.168.1.1:5432/db_name', sqldir)
    # MySQL pool (keeps 5 connections open and allows 10 more)
    db = Database('mysql+pool://username:password@/db_name', sqldir,
                  size=5, overflow=10)


Changling Cursor
----------------

If you are using **SQLite** or **PostgreSQL** you can access result 
object attribute with three different methods if you pass 
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

MySQL supports access by index only, except you pass ``dict_cursor=True`` on 
initialization. Then it supports access by key only.

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
