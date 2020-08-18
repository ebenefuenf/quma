===============
How to use quma
===============

quma reads sql files from the file system and makes them accessible as 
script objects. It passes the content of the files to a connected database
management system (DBMS) when these objects are called.

Throughout this document we assume a directory with the following structure:

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


After initialization you can run these scripts by calling members of a 
:class:`Database` or a :class:`Cursor` instance. Using the example above the 
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

To connect to a DBMS you need to instantiate an object of the :class:`Database` class
and provide a connection string and either a single path or a list
of paths to your SQL scripts.

.. code-block:: python

    from quma import Database
    db = Database('sqlite:///:memory:', '/path/to/sql-scripts')

**Note**: :class:`Database` instances are threadsafe. 

For more connection examples (e. g. PostgreSQL or MySQL/MariaDB) 
and parameters see :doc:`Connecting <connecting>`. quma also supports 
:doc:`connection pooling <pool>`.

**From now on we assume an established connection in the examples.**

Creating a cursor
-----------------

DBAPI libs like `psycopg2` or `sqlite3` have the notion of a cursor,  which is used to
manage the context of a fetch operation. quma is similar in that way. 
To execute queries you need to create a cursor instance.

quma provides two ways to create a cursor object. Either by using a context manager:

.. code-block:: python

    with db.cursor as cur:
        ...

Or by calling the ``cursor`` method of the :class:`Database` instance:

.. code-block:: python

    try:
        cur = db.cursor()
    finally:
        cur.close()


Running queries
---------------

To run the query in a sql script from the path(s) you passed to the :class:`Database` constructor
you call members of the Database instance or the cursor (*db* and *cur* from now on). 

Scripts and directories at the root of the path are translated to direct members of *db*
or *cur*. After initialisation of our example dir above, the script ``/get_admin.sql`` is
available as :class:`Script` instance ``db.get_admin`` or ``cur.get_admin``
and the directory ``/users`` as instance of :class:`Namespace`, i. e. ``db.users`` or
``cur.users``. Scripts in subfolders will create script objects as members of the corresponding
namespace: ``/users/all`` will be ``db.users.all`` or ``cur.users.all``.

When you call a :class:`Script` object, as in ``cur.user.all()`` where ``all`` is the mentioned object,
you get back a :class:`Query` instance. The simplest use is to iterate over it (see below for 
more information about the :class:`Query` class):

.. code-block:: python

    with db.cursor as cur:
        all_users = cur.users.all()
        for user in all_users:
            print(user['name'])

The same using the *db* API:

.. code-block:: python

    with db.cursor as cur:
        all_users = db.users.all(cur)

To learn what you can do with :class:`Query` objects see :doc:`The Query class <query>`.

.. Note::

    As you can see *cur* provides a nicer API where you don't have to pass the cursor when
    you call a script or a method. Then again the *db* API has the advantage of being 
    around 30% faster. But this should only be noticeable if you run hundreds or thousands
    of queries in a row for example in a loop.

    If you have cloned the `quma repository <https://github.com/ebenefuenf/quma>`_
    from github you can see the difference when you run the script 
    ``bin/cursor_vs_db.py``.


Committing changes and rollback
-------------------------------

quma does not automatically commit by default. You have to manually
commit all changes as well as rolling back if an error occurs using
the :meth:`commit()` and :meth:`rollback()` methods of the cursor.

.. code-block:: python

    try:
        cur.users.remove(id=13).run()
        cur.users.rename(id=14, name='New Name').run()
        cur.commit()
    except Exception:
        cur.rollback()

If *db* is initialized with the flag ``contextcommit`` set to ``True``
and a context manager is used, quma will automatically commit when the
context manager ends. So you don't need to call ``cur.commit()``.

.. code-block:: python

    db = Database('sqlite:///:memory:', contextcommit=True)

    with db.cursor as cur:
        cur.users.remove(id=13).run()
        cur.users.rename(id=14, name='New Name').run()
        # no need to call cur.commit()

**Note**: If you are using MySQL or SQLite some statements will automatically
cause a commit. See the `MySQL docs <http://https://dev.mysql.com/doc/refman/8.0/en/implicit-commit.html>`_
and `SQLite docs <https://docs.python.org/3/library/sqlite3.html#controlling-transactions>`_


Autocommit
~~~~~~~~~~

If you pass ``autocommit=True`` when you initialize a cursor, each query
will be executed in its own transaction that is implicitly committed.

.. code-block:: python

    with db(autocommit=True).cursor as cur:
        cur.users.remove(id=13).run()

.. code-block:: python

    try:
        cur = db.cursor(autocommit=True)
        cur.users.remove(id=13).run()
    finally:
        cur.close()


Executing literal statements
----------------------------

:class:`Database` instances provide the method :meth:`execute()`. You can pass
arbitrary sql strings. Each call will be automatically committed.
If there is a result it will be returned otherwise it returns ``None``.

.. code-block:: python

    db.execute('CREATE TABLE users ...')
    users = db.execute('SELECT * FROM users')
    for user in users:
        print(user.name)

If you want to execute statements in the context of a transaction
use the :meth:`execute` method of the cursor:

.. code-block:: python

    with db.cursor as cur:
        cur.execute('DELETE FROM users WHERE id = 13');
        cur.commit()


Accessing the DBAPI cursor and connection
-----------------------------------------

The underlying DBAPI connection and cursor objects are available as
members of the cursor instance. The connection object as ``raw_conn``
and the cursor as ``raw_cursor.cursor``.

.. code-block:: python

    # The connection
    cur.raw_conn.autocommit = True
    dbapi_cursor = cur.raw_conn.cursor()
    
    # The cursor
    cur.raw_cursor.cursor.execute('SELECT * FROM users;')
    users = cur.raw_cursor.cursor.fetchall()
    # raw_cursor wraps the real cursor. This would work as well
    cur.raw_cursor.execute('SELECT * FROM users;')
    users = cur.raw_cursor.fetchall()

All members of the ``raw_cursor.cursor`` object are also available as members 
of *cur*. Hence there should be no need to use it directly:

.. code-block:: python

    cur.execute('SELECT * FROM users;')
    users = cur.fetchall()
