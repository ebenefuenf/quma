===============
Handling errors
===============

quma raises its own exceptions instead of the driver's, so the same failure
raises the same exception with every driver. Your code doesn't need to import
the driver to handle it:

.. code-block:: python

    import quma

    try:
        with db.cursor as cur, cur.transaction():
            cur.users.add(id=1, email='ada@example.com').run()
    except quma.UniqueViolation as e:
        if e.constraint == 'uq_users_email':
            return 'This email address is already in use.'
        raise


The exceptions
--------------

.. code-block:: text

    DatabaseError             anything the database or driver reports
    ├── IntegrityError        a constraint was violated
    │   ├── UniqueViolation   also a primary key
    │   ├── ForeignKeyViolation
    │   ├── NotNullViolation
    │   ├── CheckViolation
    │   └── ExclusionViolation    PostgreSQL only
    ├── DataError             too long, out of range, of the wrong type
    ├── ProgrammingError      a syntax error, a missing table or column,
    │   │                     a missing permission
    │   └── MissingParameter  a placeholder without a value, also a KeyError
    ├── RaisedError           RAISE EXCEPTION on PostgreSQL, SIGNAL on MySQL
    │                         and MariaDB, RAISE() on SQLite
    ├── TransactionConflict   a deadlock, a serialization failure or a lock
    │                         that wasn't free in time
    └── ConnectionError       the connection can't be opened
        └── ConnectionLost    the connection broke

quma picks the class from the error code of the database. The classes of the
drivers don't tell: a CHECK violation is an ``OperationalError`` on MySQL and an
``IntegrityError`` elsewhere, and ``RAISE EXCEPTION`` is an ``InternalError`` on
psycopg2 and a ``ProgrammingError`` on psycopg. An error quma has no class for
is a plain :class:`quma.DatabaseError`.

Errors that don't come from the database have their own classes outside this
tree, for example :class:`quma.APIError` and :class:`quma.DoesNotExistError`.


What an exception holds
-----------------------

``str(e)``
    The message of the database or driver. It can quote values, so take care
    where you log it.

``e.code``
    The error code of the database: an SQLSTATE like ``'23505'`` on
    PostgreSQL, a number like ``1062`` on MySQL and MariaDB, a name like
    ``'SQLITE_CONSTRAINT_UNIQUE'`` on SQLite. ``None`` for errors the driver
    raises itself.

``e.constraint``
    The name of the violated constraint, or ``None`` if it isn't known.

    * PostgreSQL always reports it.
    * MySQL and MariaDB report it in the message only, and quma reads it from
      there, so a server that uses another language may give ``None``. A
      primary key is ``'PRIMARY'``.
    * SQLite doesn't report it, so it's always ``None``.

``e.script``
    The name of the script that failed, like ``'users/add'``. ``None`` if the
    statement doesn't come from a script file, or for a failing ``commit()``.

``e.__cause__``
    The exception of the driver, for what only it knows:

    .. code-block:: python

        except quma.IntegrityError as e:
            table = e.__cause__.diag.table_name  # PostgreSQL


Trying again
------------

A :class:`quma.TransactionConflict` means that another transaction got in the
way. Start the transaction over:

.. code-block:: python

    for attempt in range(3):
        try:
            with db.cursor as cur, cur.transaction():
                cur.accounts.withdraw(id=1, amount=10).run()
                cur.accounts.deposit(id=2, amount=10).run()
            break
        except quma.TransactionConflict:
            if attempt == 2:
                raise


What stays with the driver
--------------------------

Exceptions of the driver still reach your code from what quma doesn't run
itself:

* The object you get from psycopg's ``cur.copy()``. Other driver methods, like
  SQLite's ``cur.executescript()`` and psycopg's ``cur.stream()``, raise quma's
  exceptions.
* The connection in ``cur.raw_conn``.
* Scripts that run on a DB-API cursor you pass in, like
  ``db.users.all(raw_cursor)``.


API
---

.. autoclass:: quma.DatabaseError
