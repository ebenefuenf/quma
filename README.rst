====
quma
====

|release| |build| |docs|

quma is a small SQL database library for **Python**  and **PyPy** version 3.5 and higher.
It maps object methods to SQL script files and supports **SQLite**, **PostgreSQL**,
**MySQL** and **MariaDB**.

It also provides a simple connection pool and templating for dynamic SQL like 
conditional WHEREs.

Motivation
----------

Unlike ORMs, it allows to write SQL as it was intended and to use all features
the DBMS provides. As it uses plain SQL files you can fully utilize your database
editor or IDE to author your queries.

If you know how to best design your DDL and already have a SELECT in your mind
when data needs to be retrieved, welcome, this is for you.

It gives you back your powers you so carelessly gave away to ORMs.

Installation
------------

::

    pip install quma

Quick Start
-----------

The full documentation is available at https://quma.readthedocs.io

Given a directory with some SQL scripts e. g.:

::

    /path/to/sql/scripts
    ├── users
    │    ├── all.sql
    │    └── remove.sql
    └── get_admin.sql

You can access these scripts after connecting to the database:

.. code-block:: python

    from quma import Database

    db = Database('sqlite:///:memory:', '/path/to/sql/scripts')

    db.execute('CREATE TABLE users ...')

    with db.cursor as cur:
        all_users = cur.users.all()

        for user in all_users:
            print(user['name'])

        cur.users.remove(id=user['id']).run()
        cur.commit()

        admin = cur.get_admin().one()

License
-------

quma is released under the MIT license.

Copyright © 2018-2020 ebene fünf GmbH. All rights reserved.

.. |release| image:: https://travis-ci.org/ebenefuenf/quma.svg?branch=master
    :target: https://travis-ci.org/ebenefuenf/quma
    :alt: master Travis CI Status

.. |build| image:: https://badge.fury.io/py/quma.svg
    :target: https://badge.fury.io/py/quma
    :alt: PyPi package version

.. |docs| image:: https://readthedocs.org/projects/quma/badge/?version=latest
    :target: https://quma.readthedocs.io/en/latest/?badge=latest
    :alt: Documentation Status

