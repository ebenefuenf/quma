=======
Testing
=======

Prerequisites
-------------

In order to run the tests for *MySQL* or *PostgreSQL*
you need to create a test database:

PostgreSQL:

.. code-block:: sql

    CREATE USER quma_test_user WITH PASSWORD 'quma_test_password';
    CREATE DATABASE quma_test_db OWNER quma_test_user;

The database owner has full rights on the database and its ``public``
schema, so no further grants are required.

MySQL/MariaDB:

.. code-block:: sql

    CREATE DATABASE quma_test_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
    CREATE USER quma_test_user@localhost IDENTIFIED BY 'quma_test_password';
    GRANT ALL ON quma_test_db.* TO quma_test_user@localhost;

How to run the tests
--------------------

In the :doc:`development environment <install>`, run ``uv run pytest``
to run all tests. ``uv run pytest -m "not postgres and not mysql"`` for
all general tests. And ``uv run pytest -m "postgres"`` or
``uv run pytest -m "mysql"`` for DBMS specific tests.

To run the linter and the tests with all supported Python versions,
use tox with the `tox-uv <https://github.com/tox-dev/tox-uv>`_ plugin,
which also installs missing Python versions:

::

    uvx --with tox-uv tox run

All tox environments use the same test databases, so don't run them
in parallel.

Overwrite credentials
---------------------

If you like to use your own test database and user you can overwrite
the default credentials by setting environment variables

PostgreSQL:

* ``QUMA_PGSQL_USER``
* ``QUMA_PGSQL_PASS``
* ``QUMA_PGSQL_DB``
* ``QUMA_PGSQL_HOST``
* ``QUMA_PGSQL_PORT``

MySQL/MariaDB:

* ``QUMA_MYSQL_USER``
* ``QUMA_MYSQL_PASS``
* ``QUMA_MYSQL_DB``
* ``QUMA_MYSQL_HOST``
* ``QUMA_MYSQL_PORT``

