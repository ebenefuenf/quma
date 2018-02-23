====
Quma
====

A simple **Python** > 3.5 and **PostgreSQL** library which maps methods to
SQL scripts. Unlike ORMs, it allows to write SQL as it was intented
and to use all featuers the DBMS provides.

Installation
------------
Download the git repository and run ``python setup.py install``.


Usage
-----

Yeah!

Testing
-------

Run ``pytest`` or ``py.test``

Prerequisites
~~~~~~~~~~~~~

In order to run the tests you need to create a test database::

    CREATE USER quma_test_user WITH PASSWORD 'quma_test_password';
    CREATE DATABASE quma_test_db;
    GRANT ALL PRIVILEGES ON DATABASE quma_test_db to quma_test_user;
