=================================
Passing Parameters to SQL Queries
=================================

SQLite supports two kinds of placeholders: question marks (*qmark* style)
and named placeholders (named style). PostgreSQL/MySQL/MariaDB support 
simple (`%s`) and named (`%(name)s`) *pyformat* placeholders:

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
    cur.users.by_id.get(1)
    db.users.by_id.get(c, 1)
    # named style (:name or %(name)s)
    cur.users.by_id.get(id=1)
    db.users.by_id.get(c, id=1)
