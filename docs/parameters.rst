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


Lists
-----

A list, tuple or set directly after ``IN`` or ``NOT IN`` works with every
driver:

.. code-block:: sql

    -- sql/users/by_ids.sql
    SELECT name FROM users WHERE id IN :ids

.. code-block:: python

    cur.users.by_ids(ids=[1, 2, 3])

quma sends ``IN (%(ids__0)s, %(ids__1)s, %(ids__2)s)`` with one parameter per
element, and the driver binds each value as usual.

* Write no parentheses and nothing else between ``IN`` and the placeholder.
  ``IN (:ids)`` and ``IN /* c */ :ids`` go to the driver unchanged, and it
  rejects the list there.
* An empty list raises ``ValueError``, because SQL has no empty ``IN`` list.
  The usual replacement, ``IN (NULL)``, matches nothing with ``NOT IN`` as
  well, where you'd expect every row. Handle the empty case before the query.
* Elements are single values. Row values like ``(a, b) IN :pairs`` only work
  with psycopg2, mysqlclient and asyncmy.
* A parameter named like an element, ``ids__0``, raises ``ValueError``.

Everywhere else a list goes to the driver as it is. On PostgreSQL it's an
array there, which gives you an alternative to ``IN``:

.. code-block:: sql

    SELECT name FROM users WHERE id = ANY(:ids)
    SELECT name FROM users WHERE id <> ALL(:ids)

These work with an empty list, as you'd expect from ``IN`` and ``NOT IN``, and
need one placeholder however long the list is.

With ``placeholders='native'`` and in ``cur.execute()`` quma doesn't touch
lists. There ``IN %(ids)s`` with a tuple works with psycopg2, mysqlclient and
asyncmy, and psycopg and SQLite don't support it.


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

quma converts such SQL for each setting and raises
:class:`quma.PlaceholderError` if the results differ, naming the line and
the setting. Write the SQL so that it doesn't depend on the setting:
``E'C:\\'`` in PostgreSQL and ``''`` instead of ``\'`` for a quote in
MySQL. SQL without backslashes never depends on these settings.

On PostgreSQL, a placeholder directly after ``E``, or on the line after an
``E'...'`` string, would make its value part of an ``E'...'`` string, where a
backslash in the value can end the string. quma raises
:class:`quma.PlaceholderError` for both. Write ``E'a' || :value``. With
``placeholders='native'``, it does for a placeholder directly after ``E``, like
``E%(value)s``. It doesn't read that SQL any further, so one on the line after an
``E'...'`` string reaches the driver unchanged and has this problem, and so does
everything in ``cur.execute()``.

Some settings also change how the driver has to escape a value, and quma's tests
run hostile values under them with every driver: a value comes back as itself or
is refused.

* With psycopg2, a connection that started with
  ``standard_conforming_strings = off`` raises :class:`quma.APIError` for
  statements with values once the session turns it on, because psycopg2 can't
  escape them then. Configure the value you want for the server, the role or the
  connection's ``options``.
* In MySQL and MariaDB, a character in charsets like ``big5``, ``gbk`` or ``sjis``
  may contain a backslash byte, which makes backslash escapes depend on the charset
  the server reads. So quma sends non-ASCII text and bytes without any: it doubles
  quotes, and a value with a backslash byte becomes a hex literal, which behaves
  like the quoted string. Bytes that aren't valid text in the connection's charset
  become a binary hex literal, and asyncmy sends all bytes that way. A hex literal
  takes up twice the value's size in the statement, which counts against
  ``max_allowed_packet``, so large binary values reach that limit sooner.
* A hex literal has the charset's default collation. Under another one, set with
  ``collation='utf8mb4_unicode_ci'`` or ``SET NAMES ... COLLATE``, comparing such a
  value to a quoted string in the SQL, like ``'x' IN (:value)``, raises
  :class:`quma.ProgrammingError`. A comparison to a column works.
* A charset that Python has no codec for, like ``eucjpms`` or ``armscii8``, raises
  :class:`quma.ConnectionError` if you set it with ``charset=``, because the
  drivers can't encode for it. After ``SET NAMES`` it raises
  :class:`quma.DataError` on mysqlclient.

Set a connection's charset with ``charset='gbk'``, see :doc:`Connecting
<connecting>`, instead of ``SET NAMES gbk``: a value can't run as SQL either way,
but the driver doesn't know about ``SET NAMES``, so text may arrive garbled or
raise :class:`quma.DataError`.

Whether MySQL or MariaDB runs a versioned comment like ``/*!80000 ... */``
or ``/*M! ... */`` depends on the server's version and type, and one
server may run some of them and skip others. So SQL with such a comment
can't have placeholders or ``\:``, and quma raises
:class:`quma.PlaceholderError` for it. A ``/*! ... */`` comment without a
version runs on every server and may hold placeholders.


Types of values
---------------

Each driver decides how to send a value. What it can't send raises
:class:`quma.ProgrammingError`, and text its charset can't hold raises
:class:`quma.DataError`.

mysqlclient and asyncmy send the same for these:

* A ``bytearray``, ``memoryview`` or ``array`` is sent as its bytes.
* A ``set`` or ``frozenset`` of strings is joined with commas, for a ``SET``
  column.
* A ``tuple`` or ``list`` becomes ``('a', 'b')``, also outside of ``IN``.
* A subclass of ``int``, ``float`` or ``Decimal`` is sent as a number.
* A value of another type is sent as its ``str()`` if its class defines one, like
  ``UUID`` or ``PurePath``. A value whose only text is its ``repr()``, like a
  ``dict``, a ``range`` or a plain object, is refused.


Supported servers
-----------------

The conversion follows how PostgreSQL, MySQL and MariaDB read SQL, and
quma's tests check it against current releases of each, also with
generated SQL full of strings, comments and placeholders. Other servers
that work with the same drivers, like CockroachDB, Amazon Redshift or
TiDB, have parsers of their own, which may read strings and comments
differently. Create the database with ``placeholders='native'`` for
them: a placeholder that quma takes for SQL, but the server reads as
part of a string or comment, would let its value run as SQL.

SQLite reads ``:name`` placeholders itself and binds the values
separately, so there a placeholder in the wrong place can't let its
value run as SQL.


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
