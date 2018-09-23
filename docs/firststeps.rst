===============
How to use quma
===============

quma reads sql files from given file system paths and passes their
content as queries to a connected database management system (DBMS).

Given a directory with some SQL scripts e. g.:

::

    Scripts                │   Content 
    ───────────────────────│─────────────────────────────────────────  
    path/to/sql/scripts    │   
    ├─ users               │   
    │   ├─ all.sql         │   SELECT * FROM users
    │   ├─ by_city.sql     │   SELECT * FROM users WHERE city = :city
    │   ├─ by_id.sql       │   SELECT * FROM users WHERE id = :id
    │   ├─ rename.sql      │   UPDATE TABLE users 
    │   │                  │       SET name = :name WHERE id = :id
    │   └─ remove.sql      │   DELETE FROM users WHERE id = :id
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

Opening a connection
--------------------

To connect to a DBMS you need to instantiate an object of the ``Database`` class
and provide a connection string and either single path or a list
of paths to your SQL scripts.

.. code-block:: python

    from quma import Database
    db = Database('sqlite:///', '/path/to/sql-scripts')

**Note**: ``Database`` instances are threadsafe. 

For more connection examples 
(e. g. PostgreSQL or MySQL/MariaDB) and parameters see 
:doc:`Connecting <connecting>`

**From now on we assume an established connection in the examples.**

Creating a cursor
-----------------

Context manager:

.. code-block:: python

    with db.cursor as c:
        db.users.all(c)

Cursor method:

.. code-block:: python

    try:
        c = db.cursor()
        db.users.all(c)
    finally:
        c.close()


Fetching multiple records
--------------------------

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
