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
colon followed by a name anywhere else is one, also in a MySQL comment like
``/*! ... */``, which the server runs as SQL. Write ``\:`` for a colon that
isn't, for example in a PostgreSQL array slice like ``arr[lo\:hi]``.

There are no positional placeholders: a ``?`` would collide with
PostgreSQL's jsonb operators ``?``, ``?|`` and ``?&``. Calling a script with
positional arguments raises ``TypeError``.


Settings that change strings
----------------------------

The drivers put the values into the SQL before they send it, so a
placeholder the server sees inside a string would let its value run as
SQL. Some settings of the session change where a string ends, and quma
can't see them:

* PostgreSQL's ``standard_conforming_strings = off`` lets a backslash
  escape the quote in a standard string like ``'C:\'``.
* With MySQL's ``sql_mode`` ``NO_BACKSLASH_ESCAPES``, ``'it\'s'`` ends after
  ``it\``, and with ``ANSI_QUOTES``, ``"..."`` is a name, in which a
  backslash doesn't escape.
* Whether MySQL or MariaDB runs a versioned comment like
  ``/*!80000 ... */`` or ``/*M! ... */`` depends on the server.

quma converts such SQL for each setting and raises
:class:`quma.PlaceholderError` if the results differ, naming the line and
the setting. Write the SQL so that it doesn't depend on the setting:
``E'C:\\'`` in PostgreSQL, ``''`` instead of ``\'`` for a quote in MySQL,
and no placeholders in versioned comments. SQL without backslashes and
versioned comments never depends on these settings.


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
