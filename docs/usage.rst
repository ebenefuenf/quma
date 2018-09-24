===============
How to use quma
===============

quma reads sql files from the file system and passes their
content as queries to a connected database management system (DBMS).

Throughout this document we assume a directory with the following file structure:

::

    Scripts                │   Content 
    ───────────────────────│─────────────────────────────────────────  
    path/to/sql/scripts    │   
    ├─ users               │   
    │   ├─ all.sql         │   SELECT * FROM users
    │   ├─ by_city.sql     │   SELECT * FROM users WHERE city = :city
    │   ├─ by_id.sql       │   SELECT * FROM users WHERE id = :id
    │   ├─ remove.sql      │   DELETE FROM users WHERE id = :id
    │   └─ rename.sql      │   UPDATE TABLE users 
    │                      │       SET name = :name WHERE id = :id
    └─ get_admin.sql       │   SELECT * FROM users WHERE admin = 1


After initialization you can run these scripts by calling members of
a ``Database`` instance. Using the example above the following members 
are available: 

.. code-block:: python
    
    # 'db' is an instance of the class Database
    db.users.all(...
    db.users.by_city(...
    db.users.by_id(...
    db.users.rename(...
    db.users.remove(...
    db.get_admin(...

Read on to see how this works.

Opening a connection
--------------------

To connect to a DBMS you need to instantiate an object of the ``Database`` class
and provide a connection string and either a single path or a list
of paths to your SQL scripts.

.. code-block:: python

    from quma import Database
    db = Database('sqlite:///', '/path/to/sql-scripts')

**Note**: ``Database`` instances are threadsafe. 

For more connection examples 
(e. g. PostgreSQL or MySQL/MariaDB) and parameters see 
:doc:`Connecting <connecting>`. quma also supports 
:doc:`connection pooling <pool>`.

**From now on we assume an established connection in the examples.**

Creating a cursor
-----------------

DBAPI libs like psycopg2 or sqlite3 have the notion of a cursor,  which is used to
manage the context of a fetch operation. quma is similar in that way. 
To run queries you need to create a cursor instance.

quma provides two ways to create a cursor object. Either by using a context manager:

.. code-block:: python

    with db.cursor as c:
        ...

Or by calling the ``cursor`` method of the ``Database`` instance:

.. code-block:: python

    try:
        c = db.cursor()
    finally:
        c.close()


Running queries
---------------

To run the sql script from the path(s) you passed to the ``Database`` constructor
you call members of the Database instance (*db* from now on). 

Scripts and directories at the root of the path(s) are available as members of *db*. 
After initialisation of our example dir above, the script ``/get_admin.sql`` is
is accessible as a instance of ``Query`` (``db.get_admin``) and the directory ``/users``
as instance of ``Namespace`` (``db.users``).


.. code-block:: python

    ...
    with db.cursor as c:
        # get multiple records
        all_users = db.users.all(c)
        for user in all_users:
            print(user['name'])





Fetching a single record
------------------------

.. code-block:: python

    from quma import (
        DoesNotExistError, 
        MultipleRecordsError,
    )
    ...

    with db.cursor as c:
        try:
            user = db.users.by_id.get(c, id=13)
        except DoesNotExistError:
            print('The user does not exist')
        except MultipleRecordsError:
            print('There are multiple users with the same id')

It is also possible to get a single record by accessing its index
on the result set:

.. code-block:: python

    user = db.users.by_id(c, id=13)[0]
    # or
    users = db.users.by_id(c, id=13)
    user = users[0]

Getting data in chunks
----------------------

.. code-block:: python

    # the first two
    users = db.users.by_city.many(c, 2, city='City')
    # the next three
    users = db.users.by_city.next(c, 3)
    # the next two
    users = db.users.by_city.next(c, 2)


Changing data
-------------

.. code-block:: python

    db.users.remove(c, id=user['id'])
    db.users.rename(c, id=14, name='New Name')
    c.commit()

Executing literal statements
----------------------------

Database instances provide the method ``execude``. You can pass
arbitrary sql strings. Each call will be automatically committed.

.. code-block:: python

    db.execute('CREATE TABLE users ...')
