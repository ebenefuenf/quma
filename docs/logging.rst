=================
Logging and hooks
=================

quma knows which script a statement comes from, which drivers don't. That
makes it the right place to ask which of your scripts are slow or fail.


Logging
-------

quma logs every statement to the logger ``quma`` at level ``DEBUG``:

.. code-block:: python

    import logging

    logging.basicConfig()
    logging.getLogger('quma').setLevel(logging.DEBUG)

.. code-block:: text

    DEBUG:quma:users/by_name: 0.4 ms, rowcount 1
    SELECT email, city FROM users WHERE name = %(name)s;

Each record holds the script's name, the duration, the rowcount and the
SQL. A statement that doesn't come from a script file is called ``query``.

- The record never holds the values bound to the placeholders.
- The record of a failed statement names the type of the exception only,
  because driver messages can quote values. The exception itself reaches
  your code as usual.
- Values a :doc:`template <templates>` writes into the SQL with ``${...}``
  are part of the SQL, so they do appear.

``echo=True`` is independent of this. It prints to stdout and, on
PostgreSQL and MySQL/MariaDB, includes the values.


Hooks
-----

``on_execute`` is a function quma calls with an :class:`~quma.Execution`
after every statement, also a failed one. It works the same with
:class:`Database` and :class:`AsyncDatabase`. It's a good place for metrics
and slow-query logs:

.. code-block:: python

    log = logging.getLogger(__name__)

    def on_execute(event):
        if event.duration > 0.5:
            log.warning('Slow: %s, %.3f s', event.name, event.duration)

    db = Database(url, sqldir, on_execute=on_execute)

It runs after the statement, so a tracing span gets explicit times. With
OpenTelemetry:

.. code-block:: python

    def on_execute(event):
        end = time.time_ns()
        span = tracer.start_span(
            event.name or 'query',
            start_time=end - int(event.duration * 1e9),
        )
        span.set_attribute('db.query.text', str(event.sql))
        if event.error is not None:
            span.record_exception(event.error)
            span.set_status(trace.StatusCode.ERROR)
        span.end(end_time=end)

The rules:

- It's a plain function, also with :class:`AsyncDatabase`. quma doesn't await
  it and raises ``TypeError`` for a coroutine function. With
  :class:`AsyncDatabase` it runs on the event loop, so it must not block. Put
  slow work on a queue.
- It can't change or stop a statement.
- If it raises, quma logs the exception to the logger ``quma`` at level
  ``ERROR`` and your code gets the statement's result or error as usual. The
  statement has run at that point.
- Don't run statements on the same database in it: they'd call it again.
- ``params`` holds the bound values, so take care where you send them.


What's reported
---------------

Reported are scripts, ``cursor.query()``, ``cur.execute()``,
``cur.executemany()``, ``cur.callproc()``, ``db.execute()`` and the opening
of a :ref:`stream <streaming>`.

Not reported are:

- ``commit()`` and ``rollback()``, and the ``BEGIN``, ``COMMIT`` and savepoint
  statements of :ref:`transaction blocks <transaction-blocks>`.
- Fetching rows, and a stream's further statements.
- The pool's connection checks.
- Driver methods quma doesn't know, like SQLite's ``executescript()`` or
  psycopg's ``copy()``, and scripts run on a DB-API cursor you pass in.
- Statements that never reach the driver, like one that raises
  ``PlaceholderError``.

``duration`` is how long the driver's call took, without any wait for a
connection. What that covers differs:

- On PostgreSQL it includes receiving the rows, but not converting them to
  Python objects, which happens when they're fetched.
- On MySQL/MariaDB it includes both.
- SQLite produces rows while they're fetched, so it only covers the time to
  the first row. A slow ``SELECT`` can look fast.
- A stream's duration covers its opening only. On PostgreSQL that's a
  ``DECLARE``, which returns almost at once however slow the query is, and
  ``sql`` starts with that ``DECLARE``.


API
---

.. autoclass:: quma.Execution
