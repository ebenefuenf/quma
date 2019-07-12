=======
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

    CREATE DATABASE quma_test_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    CREATE USER quma_test_user@localhost IDENTIFIED BY 'quma_test_password';
    GRANT ALL ON quma_test_db.* TO quma_test_user@localhost;

How to run the tests
--------------------

Run ``pytest`` or ``py.test`` to run all tests. 
``pytest -m "not postgres and not mysql"`` for all general 
tests. And ``pytest -m "postgres"`` or ``pytest -m "mysql"`` 
for DBMS specific tests.

Overwrite credentials
---------------------

If you like to use your own test database and user you can overwrite
the default credentials by setting environment variables

PostgreSQL:

* ``QUMA_PGSQL_USER``
* ``QUMA_PGSQL_PASS``
* ``QUMA_PGSQL_DB``

MySQL/MariaDB:

* ``QUMA_MYSQL_USER``
* ``QUMA_MYSQL_PASS``
* ``QUMA_MYSQL_DB``

