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

You should always use placeholders (see :doc:`Parameters <parameters>`)
and restrict Mako features to control structures:

.. code-block:: sql

    SELECT * FROM
    % if table_name == 'admins':
        admins
    % else:
        users
    % endif
    WHERE
        is_active = :is_active;

See:

* https://en.wikipedia.org/wiki/SQL_injection
* https://xkcd.com/327/ (You've seen this far too often? https://xkcd.com/1053/)


Placeholders and the %
----------------------

quma converts the ``:name`` placeholders after Mako has rendered the
template, so a placeholder can also come from an expression or an included
template:

.. code-block:: mako

    <%def name="by_id()">id = :id</%def>
    SELECT name FROM users WHERE ${by_id()}

A ``%`` is a plain percent sign, like in other scripts, except as the first
non-whitespace character of a line: Mako uses it for control structures like
``if`` and ``for``. Write ``%%`` there for a literal ``%``:

.. code-block:: sql

    SELECT
        id
        %% 2 AS odd,
        name
    FROM users
    WHERE name LIKE 'A%'

With ``placeholders='native'``, templates use the driver's placeholders, and
a ``%(name)s`` placeholder must not start a line.

See: https://docs.makotemplates.org/en/latest/syntax.html#control-structures

Template files lookup
---------------------

The resolution of included or imported template files is 
accomplished by mako's class ``TemplateLookup``, which you can 
learn more about in the mako docs:
`Using TemplateLookup <https://docs.makotemplates.org/en/latest/usage.html#using-templatelookup>`_

It is initialized with the the same sql directories which are used
on ``Database`` initialization.
