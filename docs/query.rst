==================
The Query class
==================

When you call a script object it returns an instance of the
:class:`Query` class which holds the code from the script
file and the parameters passed to the script call.

Queries are executed lazily. This means you have to either call
a method of the query object or iterate over it to cause the
execution of the query against the DBMS.


Getting multiple rows from a query
----------------------------------

You can either iterate directly over the query object or call its
:meth:`all()` method to get a list of all the rows.

.. code-block:: python

    with db.cursor as cur:
        result = cur.users.by_city(city='City 1')
        for row in result:
            print(row.name)

        # calling the .all() method to get a materialized list/tuple
        user_list = cur.users.by_city(city='City 1').all()
        # is a bit faster than
        user_list = list(cur.users.by_city(city='City 1'))

When calling :meth:`all()` **MySQL** and **MariaDB** will return a tuple, **PostgreSQL**
and **SQLite** will return a list.

To get instances of your own classes or dicts instead of rows, pass the
class to :meth:`all()`, :meth:`one()` and the other fetch methods. See
:doc:`mapping`.


Getting a single row
--------------------

If you know there will be only one row in the result of a query
you can use the :meth:`one()` method to get it. quma will raise a
:exc:`DoesNotExistError` error if there is no row in the result
and a :exc:`MultipleRowsError` if there is more than one row.

.. code-block:: python

    from quma import (
        DoesNotExistError,
        MultipleRowsError,
    )
    ...

    with db.cursor as cur:
        try:
            user = cur.users.by_id(id=13).one()
        except DoesNotExistError:
            print('The user does not exist')
        except MultipleRowsError:
            print('There are multiple users with the same id')

:exc:`DoesNotExistError` and :exc:`MultipleRowsError` are also attached
to the :class:`Database` class so you can access it from the *db* instance.
For example:

.. code-block:: python

    with db.cursor as cur:
        try:
            user = cur.users.by_id(id=13).one()
        except db.DoesNotExistError:
            print('The user does not exist')
        except db.MultipleRowsError:
            print('There are multiple users with the same id')

It is also possible to get a single row by accessing its index
on the result set:

.. code-block:: python

    user = cur.users.by_id(id=13)[0]
    # or
    users = cur.users.by_id(id=13)
    user = users[0]

If you want the first row of a result set which may have more
than one row or none at all you can use the :meth:`first()` method:

.. code-block:: python

    # "user" will be None if there are no rows in the result.
    user = cur.users.all().first()

The method :meth:`value()` invokes the :meth:`one()` method, and
upon success returns the value of the first column of the row (i. e.
``fetchall()[0][0]``). This comes in handy if you are using a
``RETURNING`` clause, for example to get the id of an inserted row:

.. code-block:: sql

    -- sql/users/add.sql
    INSERT INTO users (name, email) VALUES (:name, :email) RETURNING id;

.. code-block:: python

    user_id = cur.users.add(name='User', email='user@example.com').value()

**PostgreSQL**, **SQLite** 3.35 and higher, and **MariaDB** 10.5 and higher
support ``RETURNING``. With **MySQL** use the ``lastrowid`` attribute of the
cursor instead (see `Accessing the underlying cursor`_). After inserting
several rows with one statement it holds the id of the first row.


Execute only
------------

To simply execute a query without needing its result you call
the :meth:`run()` method:

.. code-block:: python

    with db.cursor as cur:
        cur.user.add(name='User',
                     email='user@example.com',
                     city='City').run()

        # or
        query = cur.user.add(name='User',
                             email='user@example.com',
                             city='City')
        query.run()

This is handy if you only want to execute the query, e. g.
DML statements like ``INSERT``, ``UPDATE`` or ``DELETE``
where you don't need a fetch call.


Getting data in chunks
----------------------

quma supports the ``fetchmany`` method of Python's DBAPI by
providing the :meth:`many()` method of :class:`Query`.
:meth:`many()` returns an instance of :class:`ManyResult`
which implements the :meth:`get()` method which internally
calls the ``fetchmany`` method of the underlying cursor.

.. code-block:: python

    many_users = cur.users.by_city(city='City').many()
    first_two = manyusers.get(2) # the first call of get executes the query
    next_three = manyusers.get(3)
    next_two = manyusers.get(2)


Another example:

.. code-block:: python

    def users_generator()
        with db.cursor as cur:
            many_users = cur.users.all().many()
            batch = many_users.get(3) # the first call of get executes the query
            while batch:
                for result in batch:
                    yield result
                batch = many_users.get(3)

    for user in users_generator():
        print(user.name)


.. Note::

    In contrast to all other fetching methods of the query object, like
    :meth:`all()`, :meth:`first()`, or :meth:`one()`, a call of :meth:`many()`
    will not execute the query. Instead, the first call of the :meth:`get()`
    method of a `many` result object will cause the execution. Also, results
    of `many` calls are not cached and if a query was already executed
    the `many` mechanism will execute it again anyway. So keep in mind that
    already executed queries will be re-executed when :meth:`many()` is
    called after the first execution, as in:

.. code-block:: python

    all_users = cur.users.all()
    first_user = allusers.first() # query executed the first time
    many_users = allusers.many()
    first_two = manyusers.get(2) # query executed a second time

Additionally, the cache of ``all_users`` from the last example will be
invalidated after the first call of :meth:`get()`. So you should
avoid to mix `many` queries with "normal" queries.

On PostgreSQL, MySQL and MariaDB the driver loads the whole result when
the query runs, so :meth:`many()` doesn't make a large result fit in
memory. To read a large result in batches, stream it.


.. _streaming:

Streaming large results
-----------------------

:meth:`stream()` lets the server send the rows in batches while the loop
runs, so a result of any size needs the memory of one batch only:

.. code-block:: python

    with db.cursor as cur:
        for entry in cur.logs.all().stream(1000):
            archive(entry)

Without a size, a batch has 2000 rows. On PostgreSQL quma declares a
server-side cursor and fetches each batch with ``FETCH``. On MySQL and
MariaDB it reads the result with the driver's unbuffered cursor
(``SSCursor``). SQLite reads rows as they are fetched anyway.

Leaving the loop early closes the stream. So does closing its cursor or
returning its connection to the pool, and the loop then raises
:class:`quma.APIError` instead of ending early. Each call of
:meth:`stream()` runs the query again and doesn't touch the query's
cached rows.

Errors the server runs into while it produces the rows, like a division
by zero in a late row, are raised in the loop, not when it starts. The
databases add some limits:

* PostgreSQL streams in transactions only, so a cursor with
  ``autocommit=True`` raises :class:`quma.APIError`. The stream ends with
  its transaction: don't commit or roll back in the loop. The query must
  be a single ``SELECT`` or ``VALUES`` statement. Other statements can
  run between the batches, also on the same cursor. The stream keeps a
  snapshot until it ends, which stops ``VACUUM`` from removing rows
  updated or deleted in the meantime, so a stream that runs for a long
  time on a busy database can bloat its tables.
* MySQL and MariaDB can't run other statements on a connection while a
  stream is open on it. quma raises :class:`quma.APIError` for them,
  also for ``commit()``, ``rollback()`` and statements of other cursors
  on the same :doc:`carrier <carrier>`. Run them on a cursor with a
  connection of its own. A stream that is closed early still reads the
  rest of the result, because the server sends it anyway. If the loop
  stops reading for longer than ``net_write_timeout`` (60 seconds by
  default), the server can drop the connection (error 2013). For a slow
  loop, run ``SET SESSION net_write_timeout = 600`` on the cursor before
  the stream starts.

If these limits get in the way, see :ref:`large-results-in-batches`.

In async code, wrap a stream that may end early in
:func:`contextlib.aclosing` (see :doc:`async`).


.. _large-results-in-batches:

Working through a large result in batches
-----------------------------------------

A long job usually commits as it goes, so a failure doesn't lose the work
already done. A stream can't commit in its own loop, but there are two
ways around that. If the result fits in memory, :meth:`many()` is simpler:
commit between the calls of :meth:`get()`.

**Stream on one cursor, write on another.** Each cursor has its own
connection and transaction:

.. code-block:: python

    from itertools import islice

    with db.cursor as reader, db.cursor as writer:
        rows = reader.logs.all().stream(target=dict)
        while batch := list(islice(rows, 1000)):
            for entry in batch:
                writer.logs.archive(id=entry['id']).run()
            writer.commit()

The limits of a stream still apply to the reader. On PostgreSQL, MySQL and
MariaDB this needs two connections: with ``persist=True`` or a
:doc:`carrier <carrier>` the cursors share one, and it fails. On SQLite,
run one query per batch instead, because two connections fail with
"database is locked" in its default journal mode.

**Run one query per batch.** Each query continues after the last key of
the one before:

.. code-block:: sql

    -- sql/logs/after.sql
    SELECT id, message FROM logs WHERE id > :after ORDER BY id LIMIT :size;

.. code-block:: python

    with db.cursor as cur:
        after = 0
        while rows := cur.logs.after(after=after, size=1000).all(dict):
            for entry in rows:
                archive(entry)
            cur.commit()
            after = rows[-1]['id']

This works on every database, on one connection and in autocommit. Nothing
stays open on the server between the batches, so a job can run for as long
as it needs to and can resume from the last key. It needs a unique, indexed
column to sort by. There is no single snapshot: each batch sees the data as
it is at that moment, and a row inserted with a key below ``after`` is
missed.



Getting the number of rows
--------------------------

If you are only interested in the number of row in a result you can pass a
:class:`Query` object to the :func:`len()` function. quma also includes a
convenience method called :meth:`count()`. Some drivers (like pycopg2) support the
``rowcount`` property of PEP249 which specifies the number of rows that the last
execute produced. If it is available it will be used to determine the
number of rows, otherwise a fetchall will be executed and passed to :func:`len` to
get the number.

.. code-block:: python

    number_of_users = len(cur.users.all())
    number_of_users = cur.users.all().count()
    number_of_users = db.users.all(cur).count()

Like the other methods, :func:`len()`, :meth:`count()` and :meth:`exists()`
run the query only if it has not run yet. Once its rows are fetched, they
count those.


Checking if a result exists
---------------------------

To check if a query has a result or not call the :meth:`exists()` method.

.. code-block:: python

    has_users = cur.users.all().exists()

You can also use the query object itself for truth value testing:

.. code-block:: python

    all_users = cur.users.all()
    if all_users:
        user1 = allusers.first()


Ad hoc queries
--------------

To run an ad hoc query you can use the ``query`` method of the cursor:

.. code-block:: python

    with db.cursor as cur:
        sql = 'SELECT name, city FROM users WHERE email = :email;'
        user = cur.query(sql, email='user.1@example.com').one()


Prepared statements
-------------------

quma does not have a special API for prepared statements, but you can easily
use them. In the following example we use PostgreSQL's syntax.
Given a SQL script ``sqlscripts/users/prepare.sql`` with the content below ...

.. code-block:: postgresql

   PREPARE prep (varchar(128), int) AS
   SELECT name, city FROM users WHERE email = $1 AND 1 = $2;

... you can use it as shown here:

.. code-block:: python

   with db.cursor as cur:
      cur.users.pgsql_prepare().run()
      for i in range(1, 5):
            q = cur.query(f"EXECUTE prep('user.{i}@example.com', 1);")
            assert q.value() == f'User {i}'
      cur.query(f"DEALLOCATE PREPARE prep;").run()


Results are cached
------------------

As described above, quma executes queries lazily. Only after the first call
of a method or when an iteration over the query object is started,
the data will be fetched. The fetched result will be cached in the query
object. This means you can perform more than one operation on the object while
the query will not be re-executed. If you want to re-execute it, you need
to call :meth:`run()` manually.

.. code-block:: python

    with db.cursor as cur:
        all_users = cur.users.all()

        for user in all_users:
            # the result is fetched and cached on the first iteration
            print(user.name)

        # get a list of all users from the cache
        all_users.all()
        # get the first user from the cache
        all_users.first()

        # re-execute the query
        all_users.run()

        # fetch and cache the new result of the re-executed query
        all_users.all()

.. Note::

    A DB-API cursor holds the result of its latest statement only. If a
    query has run but not fetched its rows, for example after
    :meth:`count()` or :meth:`exists()` on PostgreSQL or MySQL, and
    another statement runs on the same cursor, the query can't fetch them
    anymore. quma raises :class:`quma.APIError` instead of returning the
    other statement's rows. Fetch the rows first, or call :meth:`run()`
    again.


Accessing the underlying cursor
-------------------------------

You can access the attributes of the cursor which is used to execute the
query directly on the query object.

.. code-block:: python

    with db.cursor as cur:
        removed = cur.users.remove(city='City 1').run()
        print(removed.rowcount)


Overview
--------

Class Query
~~~~~~~~~~~

.. autoclass:: quma.query.Query
    :members:

Class ManyResult
~~~~~~~~~~~~~~~~

.. autoclass:: quma.query.ManyResult
    :members:
