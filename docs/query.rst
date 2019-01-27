==================
The Query class
==================

When you call a script object it returns an instance of the 
:class:`Query` class which holds the code from the script
file and the parameters passed to the script call.

Queries are executed lazily. This means you have to either call
a method of the query object or to iterate over it to cause the
execution of the query against the DBMS.
    

Getting multiple rows from a query
----------------------------------

You can either iterate directly over the query object or call its
:meth:`all()` method to get a list of the all the rows.

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

.. Note::

    If you are using **PyPy** with the `sqlite3` driver the cast
    using the :func:`list()` function does not currently work and will always
    result in an empty list.


Getting a single row
--------------------

If you know there will be only one row in the result of a query
you can use the :meth:`one()` method to get it. quma will raise a 
:exc:`DoesNotExistError` error if there is no row in the result 
and a :exc:`MultipleRowsError` if there are returned more than one
row. 

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
``RETURNING`` clause, for example, or return the last inserted
id after an insert.

.. code-block:: python

    last_inserted_id = cur.users.insert().value()


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
    method of an `many` result object will cause the execution. Also, results
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
be invalidated after the first call of :meth:`get()`. So you should
avoid to mix `many` queries with "normal" queries.

A simpler version of :meth:`many()`
------------------------------------

If your expected result set is too large for simply iterating over
the query object or calling :meth:`all()` (as they call ``fetchall`` internally)
but you like to work with the result in a single simple loop instead of using 
:meth:`many()`, you can use the method :meth:`unbunch()`. It is a convenience
method which internally calls ``fetchmany`` with the given size. Using
:meth:`unbunch()` we can simplify the :meth:`many()` example with the
``users_generator`` from the last section:

.. code-block:: python

    with db.cursor as cur:
        for user in cur.users.all().unbunch(3)
            print(user.name)

:meth:`unbunch()` re-excutes the query and invalidates the cache on each call,
just like :meth:`many()`.



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

.. Note::

    :func:`len()` or :meth:`count()` calls must occure before fetch calls like
    :meth:`one()` or :meth:`all()`. This has to do with the internals of the DBAPI drivers.
    A fetch would overwrite the value of ``rowcount`` which would return
    ``-1`` afterwards.


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


Accessing the underlying cursor
-------------------------------

You can access the attributes of the cursor which is used to execute the
query directly on the query object.

.. code-block:: python

    with db.cursor as cur:
        added = cur.users.add(name='User', email='user.1@example.com').run()
        if added.lastrowid:
            user = cur.user.by_id(id=added.lastrowid).run()
            user.fetchone()


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
