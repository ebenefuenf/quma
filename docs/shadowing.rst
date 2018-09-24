=========
Shadowing
=========

If you pass a list of two or more directories to the ``Database``
constructor the order is important. Files from subsequent directories
in the list with the same relative path shadow (or overwrite) files
from preceding directories.

Let's say you have two different directories with SQL scripts you
like to use with quma. For example directory *one*:

::

    /path/to/sql/scripts/one
    ├── addresses
    │    ├── all.sql
    │    └── remove.sql
    ├── users
    │    ├── all.sql
    │    └── remove.sql
    ├── get_admin.sql
    └── remove_admin.sql


and directory *two*:

::

    /path/to/sql/scripts/two
    ├── users
    │    ├── all.sql
    │    └── rename.sql
    ├── create_admin.sql
    └── get_admin.sql

When you initialze quma with both directories like this:
    
.. code-block:: python

    from quma import Database

    db = Database('sqlite:///', [
        '/path/to/sql/scripts/one',
        '/path/to/sql/scripts/two',
    ])

quma creates the following members:

.. code-block:: python

                            # From directory:
    db.addresses.all        #   one
    db.addresses.remove     #   one
    db.users.all            #   two (shadows all.sql from dir one)
    db.users.remove         #   one
    db.users.rename         #   two
    db.create_admin         #   two
    db.get_admin            #   two (shadows get_admin.sql from dir one)
    db.remove_admin         #   one
