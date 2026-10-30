=================================
Passing Parameters to SQL Queries
=================================

Scripts use named placeholders, a colon followed by the parameter's name,
with every driver. Pass the values as keyword arguments:

.. code-block:: sql

    -- sql/users/by_city.sql
    SELECT name, email FROM users WHERE city = :city AND name LIKE 'A%'

.. code-block:: python

    cur.users.by_city(city='Berlin')
    db.users.by_city(cur, city='Berlin')

    # ad hoc queries work the same way
    cur.query('SELECT name FROM users WHERE id = :id', id=1).value()

Before quma runs a script it converts the placeholders to the style of the
driver, ``%(city)s`` for PostgreSQL and MySQL/MariaDB, and escapes every
``%`` for these drivers. So a ``%`` in a script is always a plain percent
sign. Templates are converted after rendering (see
:doc:`Templates <templates>`).

The conversion knows the SQL syntax of each database: a colon inside a
string, a quoted identifier, a comment or a PostgreSQL dollar-quoted string
is no placeholder, and neither is a PostgreSQL cast like ``x::text``. A
colon followed by a name anywhere else is one. Write ``\:`` for a colon that
isn't, for example in a PostgreSQL array slice like ``arr[lo\:hi]``.

There are no positional placeholders: a ``?`` would collide with
PostgreSQL's jsonb operators ``?``, ``?|`` and ``?&``. Calling a script with
positional arguments raises ``TypeError``.


Driver placeholders
-------------------

To pass scripts to the driver unchanged, create the database with
``placeholders='native'``:

.. code-block:: python

    db = Database('psycopg2://username:password@/db_name', sqldirs,
                  placeholders='native')

Scripts then use the placeholders of the driver, and positional parameters
work. SQLite supports question marks (`qmark` style) and named placeholders;
psycopg2, psycopg, mysqlclient and asyncmy support simple (``%s``) and named
(``%(name)s``) `pyformat` placeholders, and a literal ``%`` must be written
``%%``:

.. code-block:: sql

    -- SQLite qmark
    SELECT name, email FROM users WHERE id = ?
    -- named
    SELECT name, email FROM users WHERE id = :id

    -- PostgreSQL/MySQL/MariaDB pyformat
    SELECT name, email FROM users WHERE id = %s
    -- named
    SELECT name, email FROM users WHERE id = %(id)s

.. code-block:: python

    # simple style (? or %s)
    cur.users.by_id(1)
    db.users.by_id(cur, 1)

    # named style (:name or %(name)s)
    cur.users.by_id(id=1)
    db.users.by_id(cur, id=1)

Without ``placeholders='native'``, a script that contains ``%(name)s`` or
``%%`` raises :class:`quma.PlaceholderError`, which names the line. Such a
script was written for the driver, and running it would turn every ``%%``
into two percent signs. If a script needs this text literally, pass it as a
parameter.


``execute()``
-------------

``cur.execute()`` is the method of the driver's cursor (see
:doc:`How to use quma <usage>`), and ``db.execute()`` uses it, so both pass
the SQL unchanged, also without ``placeholders='native'``. They take the
driver's placeholders, and statements without parameters, like a DDL script,
keep their ``%`` as it is. For ad hoc SQL with ``:name`` placeholders use
``cur.query()``:

.. code-block:: python

    cur.query('UPDATE users SET name = :name WHERE id = :id',
              name='Jo', id=1).run()

    cur.execute('UPDATE users SET name = %(name)s WHERE id = %(id)s',
                {'name': 'Jo', 'id': 1})
