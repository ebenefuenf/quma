================
Changling cursor
================

If you are using **SQLite** or **PostgreSQL** you can access result 
object attributes using three different methods if you pass 
``changling=True`` on *db* initialization. (**MySQL** does not support it. See below)

.. code-block:: python

    db = Database('sqlite:///:memory:', sqldir, changeling=True)

    with db.cursor as c:
        user = db.users.by_id(c, 13).one()
        name = user[0]       # by index
        name = user['name']  # by key
        name = user.name     # by attribute

Shadowed superclass members
---------------------------

If a query result has a field with the same name as a member of the superclass
of the changeling (`sqlite`: :class:`sqlite3.Row`, `psycopg2`: 
:class:`psycopg2.extras.DictRow`) it shadows the original member. This means
the original member isn't accessible. You can access it anyway if you 
prefix it with an underscore '_'. 

The :class:`sqlite3.Row`, for example, has a method :func:`keys` which
lists all field names. If a query returns a field with the name 'keys'
the method is shadowed:

.. code-block:: sql

    -- /path/to/sql/scripts/users/by_id.sql
    SELECT name, email, 'the keys' AS keys FROM users WHERE id = :id;

.. code-block:: python

    row = cur.users.by_id(13).one()
    assert row.keys == 'the keys'
    
    # If you want to call the keys method of row prefix it with _
    print(row._keys()) # ['name', 'email', 'keys']

Performance
-----------

By default, changling is *False* which is slightly faster. Then SQLite 
supports access by index only. PostgreSQL by key and index (we use 
:class:`psycopg.extras.DictCursor` internally).

MySQL/MariaDB
-------------

MySQL/MariaDB supports access by index only, except you pass 
``dict_cursor=True`` on initialization. Then it supports access by 
key only.

