===========================
Dynamic SQL using Templates
===========================

quma supports rendering templates using the
`Mako template library <http://www.makotemplates.org>`_. By default,
template files must have the file extension ``*.msql``, which 
can be changed. 

Using this feature you are able to write dynamic
queries which would not be possible with SQL alone. 

A very simple example:

.. code-block:: sql

    -- sql/users/by_group.msql
    SELECT
        name,
    % if admin:
        birthday,
    % endif
        city
    FROM users
    % if not admin:
    WHERE 
        group = 'public'
    % endif

In Python you call it the same way like any other SQL query:

.. code-block:: python

    cur.users.by_group(admin=True)

Beware of SQL injections!
-------------------------

Never use templates to do a form of string concatenation as this would open 
the door to SQL injections. So never write queries like so:

.. code-block::

    SELECT * FROM
        ${table_name}
    WHERE
        is_active = ${is_active};

You should always use the parameter substitution mechanism of
the underlying driver and restrict Mako features to control structures:

.. code-block:: sql

    SELECT * FROM
    % if table_name == 'admins':
        admins
    % else:
        users
    % endif
    WHERE
        is_active = %(is_active)s;

See:

* https://en.wikipedia.org/wiki/SQL_injection
* https://xkcd.com/327/ (You've seen this far too often? https://xkcd.com/1053/)


The problem with the %
----------------------

The Mako template engine uses the %-sign to indicate control structures
like ``if`` and ``for``. Unfortunately `psycopg2` as well as `mysqlclient`
use ``%s`` for query placeholders and the ``%(variable)s`` syntax for named
placeholders. Mako does not allow the %-sign to be the first non whitespace
character in a line. As per documentation Mako should allow to escape ``%`` 
using ``%%``, but it seems it does not work. So you should simply avoid it 
in template scripts.

Wrong:

.. code-block:: sql

    SELECT * FROM
        users
    WHERE
        %(is_active)s = is_active;

Correct:

.. code-block:: sql

    SELECT * FROM
        users
    WHERE
        is_active = %(is_active)s;

See: 

* https://docs.makotemplates.org/en/latest/syntax.html#control-structures
* https://github.com/sqlalchemy/mako/issues/323

Template files lookup
---------------------

The resolution of included or imported template files is 
accomplished by mako's class ``TemplateLookup``, which you can 
learn more about in the mako docs:
`Using TemplateLookup <https://docs.makotemplates.org/en/latest/usage.html#using-templatelookup>`_

It is initialized with the the same sql directories which are used
on ``Database`` initialization.
