================
Changling Cursor
================

If you are using **SQLite** or **PostgreSQL** you can access result 
object attributes by three different methods if you pass 
``changling=True`` on db initialization. (MySQL does not support it. See below)

.. code-block:: python

    db = Database('sqlite:///', sqldir, changeling=True)

    with db.cursor as c:
        user = db.users.by_id.get(c, 13)
        name = user[0]       # by index
        name = user['name']  # by key
        name = user.name     # by attribute

By default changling is *False* which is slightly faster. Then SQLite 
supports access by index only. PostgreSQL by key and index (we use 
*psycopg.extras.DictCursor* internally).

MySQL/MariaDB supports access by index only, except you pass 
``dict_cursor=True`` on initialization. Then it supports access by 
key only.

