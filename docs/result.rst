==================
The Result class
==================

When you call a query object it returns an instance of the 
:class:`Result` class. You can use it to iterate over the
rows in the result, retrieve single rows or simply count
whats in the result.


Getting a single row
--------------------

If you now there will be only one row in the result of a query
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
upon success returns the first column of the row (i. e. 
``fetchall()[0][0]``). This comes in handy if you are using a
``RETURNING`` clause, for example, or return the last inserted
id after an insert.

.. code-block:: python

    last_inserted_id = cur.users.insert().value()


Getting data in chunks
----------------------

quma supports the ``fetchmany`` method of Python's DBAPI by
providing the :meth:`many()` method of :class:`Result`.

.. code-block:: python

    users = cur.users.by_city(city='City')
    first_two = users.many(2)
    next_three = users.many(3)
    next_tow users.many(2)


Getting the number of rows
--------------------------

If are only interested in the number of row in a result you can pass a 
:class:`Result` object to the :func:`len()` function. quma also includes a
convinience method called :meth:`count()`. Some drivers (like pycopg2) support the
``rowcount`` property of PEP249 which specifies the number of rows that the last
execute produced. If it is available it will be used to to determine the
number of rows. Otherwise a fetchall will be executed and passed to :func:`len` to
get the number.

.. code-block:: python

    number_of_users = len(cur.users.all())
    number_of_users = cur.users.all().count()
    number_of_users = db.users.all(cur).count()


.. autoclass:: quma.result.Result
    :members:
