quma Changelog
===============

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
