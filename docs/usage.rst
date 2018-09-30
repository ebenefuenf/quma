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
a ``Database`` instance or a cursor. Using the example above the 
following members are available: 

.. code-block:: python
    
    # 'cur' is a cursor instance 
    cur.users.all(...
    cur.users.by_city(...
    cur.users.by_id(...
    cur.users.rename(...
    cur.users.remove(...
    cur.get_admin(...

Read on to see how this works.

Opening a connection
--------------------

To connect to a DBMS you need to instantiate an object of the ``Database`` class
and provide a connection string and either a single path or a list
of paths to your SQL scripts.

.. code-block:: python

    from quma import Database
    db = Database('sqlite:///:memory:', '/path/to/sql-scripts')

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

    with db.cursor as cur:
        ...

Or by calling the ``cursor`` method of the ``Database`` instance:

.. code-block:: python

    try:
        cur = db.cursor()
    finally:
        cur.close()


Running queries
---------------

To run the sql script from the path(s) you passed to the ``Database`` constructor
you call members of the Database instance or the cursor (*db* and *cur* from now on). 

Scripts and directories at the root of the path(s) are available as members of *db* or *cur*. 
After initialisation of our example dir above, the script ``/get_admin.sql`` is
is accessible as an instance of ``Query`` (``db.get_admin`` or ``cur.get_admin``) and the 
directory ``/users`` as instance of ``Namespace`` (``db.users`` or ``cur.users``). 

Call members of *cur*:

.. code-block:: python

    with db.cursor as cur:
        all_users = cur.users.all()

The same using the *db* API:

.. code-block:: python

    with db.cursor as cur:
        all_users = db.users.all(cur)

As you can see *cur* provides a nicer API as you don't have to pass the cursor when
you call a query or a method. Then again the *db* API has the advantage of being 
around 30% faster. But this should only be noticable if you run hundreds or thousands
of queries in a row for example in a loop.


Getting a single record
-----------------------

If you now there will be only one record in the result of a query
you can use the ``get`` method to get it. quma will raise a 
``DoesNotExistError`` error if there is no record in the result 
and a ``MultipleRecordsError`` if there are returned more than one
record. 

.. code-block:: python

    from quma import (
        DoesNotExistError, 
        MultipleRecordsError,
    )
    ...

    with db.cursor as cur:
        try:
            user = cur.users.by_id.get(id=13)
        except DoesNotExistError:
            print('The user does not exist')
        except MultipleRecordsError:
            print('There are multiple users with the same id')

``DoesNotExistError`` and ``MultipleRecordsError`` are also attached
to the ``Database`` class so you can access it from the db instance.
For example:

.. code-block:: python

    with db.cursor as cur:
        try:
            user = cur.users.by_id.get(id=13)
        except db.DoesNotExistError:
            print('The user does not exist')
        except db.MultipleRecordsError:
            print('There are multiple users with the same id')

It is also possible to get a single record by accessing its index
on the result set:

.. code-block:: python

    user = cur.users.by_id(id=13)[0]
    # or
    users = cur.users.by_id(id=13)
    user = users[0]

If you want the first record of a result set which may have more
than one record you can use the ``first`` method:

.. code-block:: python

    user = cur.users.all.first()

``value`` returns the first value of the first row (i. e. 
``fetchall()[0][0]``). This comes in handy if you are using a
``RETURNING`` clause, for example, or return the last inserted
id after a insert.

.. code-block:: python

    last_inserted_id = cur.users.insert.value()


Getting data in chunks
----------------------

quma supports the ``fetchmany`` method of Python's DBAPI by
providing the ``many`` and ``next`` methods of ``Query``.

.. code-block:: python

    # the first two
    users = cur.users.by_city.many(2, city='City')
    # the next three
    users = cur.users.by_city.next(3)
    # the next two
    users = cur.users.by_city.next(2)


Getting the number of records
-----------------------------

If you are only interested in the number of records in a result
set  you can call the ``count`` method:

.. code-block:: python

    number_of_users = cur.users.all.count()
    number_of_users = db.users.all.count(cur)


Committing changes and rollback
-------------------------------

quma does not automatically commit by default. You have to manually
commit all changes. As well as rolling back if a error occurs.

.. code-block:: python

    try:
        cur.users.remove(id=13)
        cur.users.rename(id=14, name='New Name')
        cur.commit()
    except Exception:
        cur.rollback()

**Note**: If you are using MySQL or SQLite some statements will automatically
cause a commit. See the `MySQL docs <http://https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html>`_
and `SQLite docs <https://docs.python.org/3/library/sqlite3.html#controlling-transactions>`_

If *db* is initialized with the flag ``contextcommit`` set to ``True``
and a context manager is used, quma will automatically commit when the
context manager ends. So you don't need to call ``cur.commit()``.

.. code-block:: python

    db = Database('sqlite:///:memory:', contextcommit=True)

    with db.cursor as cur:
        cur.users.remove(id=13)
        cur.users.rename(id=14, name='New Name')
        # no need to call cur.commit()


Autocommit
~~~~~~~~~~

If you pass ``autocommit=True`` on cursor init each statement (query) 
will be executed in its own transaction that is implicitly committed.

.. code-block:: python

    with db(autocommit=True).cursor as cur:
        cur.users.remove(id=13) 

.. code-block:: python

    try:
        cur = db.cursor(autocommit=True)
        cur.users.remove(id=13) 
    finally:
        cur.close()


Executing literal statements
----------------------------

Database instances provide the method ``execute``. You can pass
arbitrary sql strings. Each call will be automatically committed.
If there is a result it will be returned otherwise it returns ``None``.

.. code-block:: python

    db.execute('CREATE TABLE users ...')
    users = db.execute('SELECT * FROM users')
    for user in users:
        print(user.name)
