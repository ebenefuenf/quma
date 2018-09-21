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


Usage
=====

If you like to use SQLite, Python has everything covered. To use PostgreSQL
you need to install *psycopg2* or *psycopg2cffi*. For MySQL it's *mysqlclient*.

If you want to use templates install *mako*.

Example:

Given a directory with some SQL scripts:

    /home/user/sql-scripts
    ├── users
    │    ├── all.sql
    │    ├── by_id.sql
    │    ├── rename.sql
    │    └── remove.sql
    └── get_admin.sql

.. code-block:: python

    from quma import Database

    db = Database('sqlite:////path/to/db.sqlite')

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
