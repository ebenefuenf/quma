====
Rows
====

Rows work the same with every driver: by index and by key. Pass ``changeling=True``
when you create the database to also reach columns as attributes:

.. code-block:: python

    db = Database('sqlite3:///:memory:', sqldir, changeling=True)

    with db.cursor as cur:
        user = cur.users.by_id(id=13).one()
        name = user[0]       # by index
        name = user['name']  # by key
        name = user.name     # by attribute, with changeling=True only

A row is a list with some methods of a dict, so these work too:

.. code-block:: python

    email, name = user
    user['name'] = 'New Name'
    'name' in user       # looks for a column, not for a value
    user.keys()          # the column names
    user.values()
    user.items()
    user.get('nope', 13)
    user.copy()          # a dict of the row
    dict(user)

A missing key raises :exc:`KeyError`, and a missing attribute
:exc:`AttributeError`. If two columns have the same name, the last one wins.

To get other types than rows, like real dicts or your own classes, see
:doc:`mapping <mapping>`: ``cur.users.list().all(dict)``.

Shadowed list members
---------------------

With ``changeling=True``, a column with the name of a member of the row shadows that
member. You can reach the member anyway if you prefix it with an underscore:

.. code-block:: sql

    -- /path/to/sql/scripts/users/by_id.sql
    SELECT name, email, 'the keys' AS keys FROM users WHERE id = :id;

.. code-block:: python

    row = cur.users.by_id(id=13).one()
    assert row.keys == 'the keys'

    # If you want to call the keys method of row prefix it with _
    print(list(row._keys())) # ['name', 'email', 'keys']

Setting an attribute changes the column of that name. An unknown name raises
:exc:`KeyError`, because a row has no room for new columns.

Performance
-----------

Building rows costs 0.5 to 0.7 microseconds per row more than the plain tuples that
sqlite3 and mysqlclient produce, measured with four columns. It hardly matters next
to the query. For a large result, :meth:`stream() <quma.query.Query.stream>` saves
more than any row type can.

psycopg2's rows are its own :class:`psycopg2.extras.DictRow`, which the rows of the
other drivers imitate.
