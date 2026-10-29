===============
quma Changelog
===============

Unreleased
----------

- Add an async API for asyncio applications: ``AsyncDatabase``,
  ``AsyncCursor`` and ``AsyncQuery``, with psycopg 3 (``psycopg://`` and
  ``psycopg+pool://``) and, for MySQL and MariaDB, asyncmy
  (``asyncmy://`` and ``asyncmy+pool://``, extra ``asyncmy``). Calls that
  talk to the database are awaited;
  SQL directories, namespaces, templates, rows and mapping work as in
  sync code. See the new docs page "Async", which also shows how to use
  it with Starlette, FastAPI and Litestar.
- ``quma`` exports ``Cursor``, ``AsyncDatabase``, ``AsyncCursor`` and
  ``connect_async()``.
- With ``contextcommit``, a cursor's ``with`` block now rolls back when it
  raises. Before, quma committed the statements that ran before the
  error. If the block raises to signal success, such as a redirect, call
  ``cur.commit()`` before raising.
- A cursor's ``with`` block returns its connection to the pool even if
  the commit at its end fails. If the rollback after an error fails, for
  example on a lost connection, the block's own exception is raised.
- Fix a cursor keeping its connection out of the pool when closing the
  driver cursor fails, for example when a later statement of a
  multi-statement MySQL query fails.
- Fix a pool losing a slot when opening a cursor fails on a connection
  the server has closed, for example without ``pessimistic=True``. A
  carrier no longer keeps that connection either.
- Fix threads waiting for a pool connection staying blocked when the
  pool discarded a broken connection, for example after a database
  restart. They woke only at the pool's timeout, or never without one.
  Like the async pool, the pool now limits its connections with a
  semaphore instead of a queue.
- Fix a pool losing a slot when enabling autocommit on an idle
  connection fails.
- Fix connections returned to a pool after ``Database.close()`` staying
  open in the closed pool. The pool now closes them.
- ``count()``, ``exists()`` and ``len()`` no longer re-execute a query
  that has already run. They count its fetched rows or use the row count
  of its run. Before, they ran it again, which repeated writes such as
  ``INSERT ... RETURNING`` and dropped its cached rows. Call ``run()`` to
  re-execute a query.
- Fix ``one()`` checking the row count of the cursor's latest query
  instead of its own. Once another query ran on the same cursor, it
  raised ``MultipleRowsError`` for a single row or returned the first of
  several rows.
- Fix ``cache=True`` running the script of a shadowed SQL directory
  instead of the masking one when both have a script of the same name.

Version 0.4.0
-------------

Released on October 28th 2026

- Map rows to objects: ``one()``, ``first()``, ``all()``, ``unbunch()``
  and ``ManyResult.get()`` accept a target and return instances of it.
  Targets are classes, whose constructor parameters are filled from the
  columns of the same name, ``dict``, ``TypedDict``, classes with a
  ``from_row()`` classmethod, and resolvers returning the class per row.
  New exceptions ``MappingError`` and ``MissingColumnError``.

Version 0.3.0
-------------

Released on October 28th 2026

- The scheme of a database URL names the driver package:
  ``psycopg2://``, ``psycopg://`` (psycopg 3), ``mysqlclient://`` and
  ``sqlite3://``, each also with ``+pool``. The schemes
  ``postgresql://``, ``mysql://`` and ``sqlite://`` were removed.
- The extras ``postgres`` and ``mysql`` were renamed to ``psycopg2`` and
  ``mysqlclient``. ``psycopg`` installs psycopg 3.
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
- Fix ``autocommit=True`` failing on PostgreSQL with ``persist=True`` and
  ``pessimistic=True``. The connection check no longer leaves its own
  transaction open.
- Fix a connection pool returning ``None`` instead of a connection when
  another thread took the last overflow slot at the same time.
- Fix a pool losing a slot for every connection that broke while in
  use, for example during a database restart. Once all slots were lost,
  checkouts timed out or waited forever. Returning a broken connection
  now discards it instead of raising, which also no longer hides the
  error that broke it behind psycopg2's ``InterfaceError``.
- Fix a pool with ``pessimistic=True`` losing a slot whenever a
  connection failed the check and reconnecting failed too, for example
  while the database server was down.
- Fix a pool with ``pessimistic=True`` failing to replace a MySQL
  connection that was already closed. The checkout raised and the pool
  lost the connection's slot.
- Fix ``pessimistic=True`` never replacing a closed psycopg2 connection,
  for example one that lost the server connection during a query. A
  persistent connection kept failing until the application restarted.
- Fix ``with db.cursor() as cur`` opening a second connection and never
  returning the first. The ``with`` block now uses the connection opened
  by the call, including its ``autocommit`` setting.
- Errors in a namespace's ``__init__.py`` are no longer hidden. quma
  used the default namespace instead when one of them was an
  ``AttributeError`` or ``FileNotFoundError``. A module without the
  expected class still gets the default namespace.
- Close a persistent connection that fails the ``pessimistic`` check
  before replacing it.
- ``Database.close()`` no longer raises ``APIError`` for connections that
  are neither persistent nor pooled, and can be called more than once.
- Add support for psycopg 3 with the ``psycopg://`` scheme.
- An unknown URL scheme raises ``ValueError`` listing the supported
  schemes instead of ``ModuleNotFoundError``.
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
