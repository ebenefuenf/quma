===============
quma Changelog
===============

Unreleased
----------

- Add type annotations for the public API and ship them (``py.typed``).
  Namespaces, scripts and rows are dynamic and typed as ``Any``.
- ``Database()`` declares its own options as keyword arguments. All
  other keyword arguments are still passed on to the connection.
- Opening a cursor of a closed database raises ``APIError``.
- Fix ``Database.execute()`` keeping its connection checked out. With a
  pool every call used up a connection until the pool was exhausted.
- Fix closing a cursor twice returning its connection to the pool twice,
  for example ``cur.close()`` inside a ``with`` block as shown in the
  docs. Two later checkouts then shared the same connection.
- ``commit()`` and ``rollback()`` on a closed cursor raise ``APIError``
  instead of using a connection that may already be in use elsewhere.
- Fix a ``TypeError`` raised while rendering a template being reported
  as missing Mako.
- Fix ``autocommit=True`` being ignored when a connection pool reused a
  connection.
- Fix a connection pool returning ``None`` instead of a connection when
  another thread took the last overflow slot at the same time.
- Fix ``with db.cursor() as cur`` opening a second connection and never
  returning the first. The ``with`` block now uses the connection opened
  by the call, including its ``autocommit`` setting.
- Close a persistent connection that fails the ``pessimistic`` check
  before replacing it.
- ``Database.close()`` no longer raises ``APIError`` for connections that
  are neither persistent nor pooled, and can be called more than once.
- Add support for psycopg 3 with the ``psycopg://`` scheme.
- Add the ``psycopg2://`` scheme for PostgreSQL. ``postgresql://``
  remains an alias for it.
- Add support for Python 3.14 and 3.15.
- Remove support for Python 3.10.
- Remove support for PyPy.


Version 0.2.2
-------------

Released on September 18th 2026

- Fix release of carriers that never obtained a connection.


Version 0.2.1
-------------

Released on October 28th 2025

- Set autocommit only to True if the passed argument is a boolean.


Version 0.2.0
-------------

Released on October 28th 2025

- Add support for Python 3.13.
- Remove support for Python and PyPy <3.10.


Version 0.1.1
-------------

Released on May 6th 2025

- Bugfix release: Ignore ``__pycache__`` directories when loading
  namespaces.

Version 0.1.0
-------------

Released on August 16th 2020

- Raise ``quma.ConnectionError`` when a connection fails.


Version 0.1.0b4
---------------

Released on October 10th 2019

- Bugfix release: When carrier and pool were used together the pool
  was not cleaned up properly.


Version 0.1.0b3
---------------

Released on October 9th 2019

- Revised tests. They where failing in CI with 0.1.0b2 as Travis uses
  MySQL 5 and prepared statements obvisually doesn't work with MySQLdb
  and this server version.


Version 0.1.0b2
---------------

Released on October 8th 2019

- You can now use original connection parameters of the DB API adapter
  which will be passed to the adapters ``connect`` function.

  Example:

  ``db = Database('mysql://...', sqldir, charset='utf8')``

  will result in

  ``MySQLdb.connect(host='...', db='...', charset='utf8')``

  Where ``charset`` is part of MySQLdb's API and not part of quma's.
- Objects which are passed as carrier are not altered anymore. Previously
  carriers had been added an attribute called ``__quma_conn__``.
- Mako templates are now set up using mako's ``TemplateLookup`` which
  is initialized with the sql directories.
- Add method ``.query()`` to ``Cursor``.
- Add "prepared statements" section to docs.

Version 0.1.0b1
---------------

Released on January 27th 2019

- Rename ``Database`` parameter ``show`` to ``echo``.
- When ``echo`` is set to ``True`` *PostgreSQL* and *MySQL/MariaDB*
  connections now print the query after argument binding which means
  placholders are replaced with parameter values.

Version 0.1.0a5
---------------

Released on November 16th 2018

- Fix ``query.exists()``: Return DBAPI's ``rowcount`` if available.

Version 0.1.0a4
---------------

Released on October 19th 2018

- Make the cursor as first parameter of public custom namespace methods
  mandatory. Automatically pass it when the method is called via the
  *cur* api.
- Fix ``query.count()``/``len(query)``: Return DBAPI's ``rowcount`` if
  available. Don't fetch the result when these methods are called anymore.
  Calls of count have overwritten the value of ``rowcount`` and set it
  to ``-1``.

Version 0.1.0a3
---------------

Released on October 10th 2018

- Change method calling style from ``cur.namespace.query.first()`` to
  ``cur.namespace.query().first()``.
- Rename ``quma.query.Query`` to ``quma.script.Script``.
- Rename ``MultipleRecordsError`` to ``MultipleRowsError``.
- Introduce the new ``quma.query.Query`` class. An instance is now returned
  from a script object call.
- Add ``.all()`` method to ``Query``.
- Add ``.exists()`` method to ``Query``.
- Execute queries lazily.
- Cache query results.
- Support truth value testing of query objects.
- Enable access to members of the underlying cursor in the ``Query`` class.
- Introduce the ``key`` parameter of ``value()``.
- Support accessing the result of query objects by index ``cur.namespace.query()[0]``.
- Add ``.unbunch()`` method to ``Query``.

Version 0.1.0a2
---------------

Released on October 2nd 2018

- Shadow changeling superclass members
  (`see <https://quma.readthedocs.io/en/latest/changeling.html>`_)

Version 0.1.0a1
---------------

Released on October 1st 2018

First public alpha release.
