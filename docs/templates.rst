=========
Templates
=========

quma supports rendering templates using the
`Mako template library <http://www.makotemplates.org>`_. By default
template files must have the file extension ``msql`` which 
can be overwritten. 

Using this feature you are able to write dynamic
queries which would not be possible with SQL alone. 
**Beware of SQL injections**.

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

In Python you call it the same way like simple SQL queries:

.. code-block:: python

    cur.users.by_group(admin=True)

