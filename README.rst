====
Quma
====

A simple **Python** > 3.5 and **SQLite**/**PostgreSQL**/**MySQL** library 
which maps methods to SQL scripts. Unlike ORMs, it allows to write SQL as
it was intented and to use all featuers the DBMS provides.

Installation
------------

Download the git repository and run ``python setup.py install``.


Usage
-----

If you like to use SQLite, Python has everything covered. To use PostgreSQL
you need to install *psycopg2* or *psycopg2cffi*. For MySQL it's *mysqlclient*.

And then **Yeah**!

Testing
-------

**Prerequisites**: In order to run the tests for *MySQL* or *PostgreSQL*
you need to create a test database:

PostgreSQL::

    CREATE USER quma_test_user WITH PASSWORD 'quma_test_password';
    CREATE DATABASE quma_test_db;
    GRANT ALL PRIVILEGES ON DATABASE quma_test_db to quma_test_user;

MySQL/MariaDB::

    CREATE DATABASE quma_test_db;
    CREATE USER quma_test_user@localhost IDENTIFIED BY 'quma_test_password';
    GRANT ALL ON quma_test_db.* TO quma_test_user@localhost;

How to run the tests
~~~~~~~~~~~~~~~~~~~~

Run ``pytest`` or ``py.test`` to run all tests. 
``pytest -m "not postgres and not mysql"`` for all general 
tests. And ``pytest -m "postgres"`` or ``pytest -m "mysql"`` 
for DBMS specific tests.
