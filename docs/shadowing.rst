=========
Shadowing
=========

If you pass a list of two or more directories to the :class:`Database`
constructor, the order is important. Files from subsequent directories
in the list with the same relative path will shadow (or overwrite) files
from preceding directories.

Let's say you have two different directories with SQL scripts you
like to use with quma. For example directory `first`:

::

    /path/to/sql/scripts/first
    ├── addresses
    │    ├── all.sql
    │    └── remove.sql
    ├── users
    │    ├── all.sql
    │    └── remove.sql
    ├── get_admin.sql
    └── remove_admin.sql


and directory `second`:

::

    /path/to/sql/scripts/second
    ├── users
    │    ├── all.sql
    │    └── rename.sql
    ├── create_admin.sql
    └── get_admin.sql

When you initialize quma with both directories like this:
    
.. code-block:: python

    from quma import Database

    db = Database('sqlite3:///:memory:', [
        '/path/to/sql/scripts/first',
        '/path/to/sql/scripts/second',
    ])

quma creates the following members:

.. code-block:: python

                             # From directory:
    cur.addresses.all        #   first
    cur.addresses.remove     #   first
    cur.users.all            #   second (shadows all.sql from dir first)
    cur.users.remove         #   first
    cur.users.rename         #   second
    cur.create_admin         #   second
    cur.get_admin            #   second (shadows get_admin.sql from dir first)
    cur.remove_admin         #   first


Names that are taken
--------------------

A cursor has members of its own, like ``commit``, ``query`` or ``transaction``, and
those of every DB-API cursor, like ``execute`` or ``description``. ``cur.transaction``
always means the method, so it can't reach a SQL directory or a script in the root
of that name, and quma warns about such a name when it registers the directory.
Rename it, or go through the database, which has fewer members:

.. code-block:: python

    db.transaction.by_id(cur, id=1)

The few names both have, like ``close`` or ``execute``, work like this:

.. code-block:: python

    db.namespaces['close'].by_id(cur, id=1)

Attributes that only some drivers have, like ``copy`` on psycopg or ``name`` on
psycopg2, don't get in the way: a SQL directory or script of that name wins, on
every driver, and ``cur.raw_cursor.copy`` still reaches the driver's.

A :doc:`custom namespace <namespaces>` with a method of the name of a script in its
directory shadows that script too. It's available with an underscore:
``cur.users._all()``.
