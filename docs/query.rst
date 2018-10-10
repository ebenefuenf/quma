==================
The Query class
==================

When you call a script object it returns an instance of the 
:class:`Query` class which holds the code from the script
file and the parameters passed to the script call.

Queries are executed lazily. This means you have to either call
a method of the query object or iterate over it.
    

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
which implements the :meth:`next()` method which also
returns a :class:`ManyResult` object. 

.. code-block:: python

    frist_two = cur.users.by_city(city='City').many(2)
    assert len(first_two) == 2
    next_three = first_two.next(3)
    assert len(next_three) == 2
    next_two = next_three.next(2)


Another example:

.. code-block:: python

    def users_generator()
        with db.cursor as cur:
            manyusers = cur.users.all().many(3)
            while len(manyusers):
                for result in manyusers:
                    yield result
                manyusers = manyusers.next(3)


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


Checking if a result exists
---------------------------

To check if a query has a result or not call the :meth:`exists()` method.

.. code-block:: python

    has_users = cur.users.all().exists()

You can also use the query object itself for truth value testing:

.. code-block:: python

    allusers = cur.users.all()
    if allusers:
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
        allusers = cur.users.all()

        for user in allusers:
            # the result is fetched and cached on the first iteration
            print(user.name)

        # get a list of all users from the cache
        allusers.all()
        # get the first user from the cache
        allusers.first()

        # re-execute the query
        allusers.run()

        # fetch and cache the new result of the re-executed query
        allusers.all()

Overview
--------

.. autoclass:: quma.query.Query
    :members:
