====
quma
====

quma is a small SQL database library for **Python** version 3.5 and higher.
It maps object methods to SQL script files and supports **SQLite**, **PostgreSQL**,
**MySQL** and **MariaDB**.

Unlike ORMs it allows to write SQL as it was intented and to use all featuers
the DBMS provides. As it uses plain SQL files you can fully utilize your database GUI tool.

It also provides a simple connection pool.

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
    
You can access these scripts after connecting to the database (in this example
we use a SQLite in memory database):
    
.. code-block:: python

    from quma import Database

    db = Database('sqlite:///', '/path/to/sql/scripts')

    db.execute('CREATE TABLE users ...')

    with db.cursor as c:
        all_users = db.users.all(c)

        for user in all_users:
            print(user['name'])

        db.users.remove(c, id=user['id'])
        c.commit()

        admin = db.get_admin(c)

License
-------

Pony ORM is released under the MIT license.

Copyright © 2018 ebene fünf GmbH. All rights reserved.
