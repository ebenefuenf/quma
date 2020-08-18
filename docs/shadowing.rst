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

    db = Database('sqlite:///:memory:', [
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
