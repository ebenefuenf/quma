quma Changelog
===============

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
